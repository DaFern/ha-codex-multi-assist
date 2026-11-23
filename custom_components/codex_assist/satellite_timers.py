"""Fixed local timers and a separately authorised cross-satellite alert adapter.

Never expose Core's global timer matching: it can select a timer on another device.
The small volatile journal retains finished timer objects only to send a native
cancellation event after Core has removed them. It stores no speaker authority.
"""

import inspect
import re
import time
from dataclasses import dataclass

import probatio
from homeassistant.components.intent.const import TIMER_DATA
from homeassistant.components.intent.timers import (
    TimerEventType,
    TimerInfo,
    TimerManager,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm

DATA_TIMERS = "codex_assist_satellite_timers"
MAX_SECONDS = 7 * 24 * 60 * 60
MAX_TIMERS = 32
MAX_RETAINED = 1024
FINISHED_RETENTION_SECONDS = 60 * 60


@dataclass
class _RetainedTimer:
    identity: tuple
    manager: TimerManager
    handler: object
    timer: TimerInfo


def _identity(entry):
    if entry is None or entry.platform != "esphome" or entry.disabled_by is not None:
        return None
    if not entry.device_id or not entry.config_entry_id:
        return None
    return (entry.id, entry.unique_id, entry.config_entry_id, entry.device_id)


def _failure(message):
    return llm.ToolResult(data={"error": message}, error=True)


class SatelliteTimerTool(llm.Tool):
    """Fixed local countdown controls plus separately authorised remote cancellation."""

    name = "codex_assist__satellite_timer"
    title = "Manage satellite timers"
    integration = "codex_assist"
    description = (
        "Start, list, query, pause, resume, adjust or cancel countdown timers here. "
        "Use hours/minutes/seconds for a new duration or an add_time/remove_time amount; "
        "use name and/or start_hours/start_minutes/start_seconds to select an existing timer. "
        "For cancel/pause/resume/status, hours/minutes/seconds can also select its start duration. "
        "Ask which timer when clarification_required is returned. "
        "Use stop for a ringing timer: select only one positively reported alert across "
        "permitted enrolled satellites, never infer ringing from expiry. "
        "For cancel or stop, satellite may explicitly name a permitted satellite or room. "
        "cancel_all is local unless the user explicitly requests scope=all_permitted. "
        "No remote start/pause/resume/adjust, delayed commands or arbitrary service calls."
    )
    annotations = llm.ToolAnnotations(
        read_only=False, destructive=True, idempotent=False, open_world=False,
    )
    parameters = probatio.Schema({
        probatio.Required("action"): probatio.In((
            "start", "cancel", "cancel_all", "status", "list", "pause", "resume",
            "add_time", "remove_time", "stop",
        )),
        probatio.Optional("hours"): probatio.All(int, probatio.Range(min=0, max=168)),
        probatio.Optional("minutes"): probatio.All(int, probatio.Range(min=0, max=10080)),
        probatio.Optional("seconds"): probatio.All(int, probatio.Range(min=0, max=MAX_SECONDS)),
        probatio.Optional("name"): probatio.All(str, probatio.Length(min=1, max=80)),
        probatio.Optional("start_hours"): probatio.All(int, probatio.Range(min=0, max=168)),
        probatio.Optional("start_minutes"): probatio.All(int, probatio.Range(min=0, max=10080)),
        probatio.Optional("start_seconds"): probatio.All(
            int, probatio.Range(min=0, max=MAX_SECONDS),
        ),
        probatio.Optional("satellite"): probatio.All(str, probatio.Length(min=1, max=128)),
        probatio.Optional("scope"): probatio.In(("local", "all_permitted")),
    })

    def __init__(self, hass, authorization):
        self._auth = authorization
        self._identity = _identity(er.async_get(hass).async_get(authorization.satellite_id))
        self._manager = hass.data.get(TIMER_DATA)
        self._handler = (
            self._manager.handlers.get(self._identity[-1])
            if self._identity and isinstance(self._manager, TimerManager) else None
        )
        self.validate_references = None
        self.remaining_actions = MAX_TIMERS
        self.claim_effect = None
        self._effects = set()
        self._clarification_required = False
        self.remote_targets = None

    def available(self, hass):
        """Recheck source/registry/native handler identity, without any model input."""
        try:
            return bool(
                self._auth.valid()
                and self._identity is not None
                and _identity(er.async_get(hass).async_get(self._auth.satellite_id))
                == self._identity
                and isinstance(self._manager, TimerManager)
                and hass.data.get(TIMER_DATA) is self._manager
                and callable(self._handler)
                and self._manager.handlers.get(self._identity[-1]) == self._handler
            )
        except Exception:
            return False

    def _journal(self, hass):
        journal = hass.data.setdefault(DATA_TIMERS, {})
        now = time.monotonic_ns()
        for timer_id, record in tuple(journal.items()):
            if record.manager is not self._manager or (
                record.manager.timers.get(timer_id) is not record.timer
                and (
                    record.timer.is_active or record.timer.seconds != 0
                    or now - record.timer.updated_at > FINISHED_RETENTION_SECONDS * 1_000_000_000
                )
            ):
                del journal[timer_id]
        return journal

    def _local_timers(self, journal):
        device_id = self._identity[-1]
        # Active/paused timers on the same physical satellite are shared. Delayed
        # commands and all other devices are excluded before any matching occurs.
        local = {
            timer.id: timer for timer in self._manager.timers.values()
            if timer.device_id == device_id and not timer.conversation_command
        }
        for timer_id, record in journal.items():
            if (
                record.identity == self._identity and record.handler == self._handler
                and record.timer.device_id == device_id
                and not record.timer.conversation_command
            ):
                local.setdefault(timer_id, record.timer)
        return list(local.values())

    def _claim(self, action, timer_id, extra=None):
        effect = (action, self._identity[-1], timer_id, extra)
        if effect in self._effects or (
            self.claim_effect is not None
            and not self.claim_effect("intent", action + "_timer", {"selection": list(effect)})
        ):
            return False
        self._effects.add(effect)
        return True

    def _cancel(self, timer, journal):
        if self._manager.timers.get(timer.id) is timer:
            self._manager.cancel_timer(timer.id)
            action = "cancelled"
        else:
            self._handler(TimerEventType.CANCELLED, timer)
            action = "dismissal_requested"
        journal.pop(timer.id, None)
        return action

    async def async_call(self, hass, tool_input, llm_context):
        auth = self._auth
        if (
            llm_context.context is not auth.context
            or llm_context.assistant != "conversation"
            or not self.available(hass)
        ):
            return _failure("Timer control is not authorised.")
        # The factory supplies its complete live native/RBAC projection validator,
        # not role-selector metadata or a cached entity/role grant.
        if self.validate_references is None or not await self.validate_references():
            return _failure("Timer control is not authorised.")
        args = self.parameters(tool_input.tool_args)
        action = args["action"]
        parts = [args.get(key, 0) for key in ("hours", "minutes", "seconds")]
        start_parts = [args.get("start_" + key, 0) for key in ("hours", "minutes", "seconds")]
        if any(type(part) is not int for part in [*parts, *start_parts]):
            return _failure("Use whole numbers for the timer duration.")
        duration = parts[0] * 3600 + parts[1] * 60 + parts[2]
        start_duration = start_parts[0] * 3600 + start_parts[1] * 60 + start_parts[2]
        has_duration = any(key in args for key in ("hours", "minutes", "seconds"))
        has_start = any("start_" + key in args for key in ("hours", "minutes", "seconds"))
        adjusting = action in {"add_time", "remove_time"}
        if (has_duration and not 0 < duration <= MAX_SECONDS) or (
            (action == "start" or adjusting) and not has_duration
        ) or (has_start and not 0 < start_duration <= MAX_SECONDS):
            return _failure("Give a timer duration between one second and seven days.")
        if action == "start" and has_start or has_start and has_duration and not adjusting:
            return _failure("Use one starting-duration selector, separate from an adjustment.")
        if action == "cancel_all" and (
            has_start or has_duration or "name" in args
        ):
            return _failure("Cancel-all cannot have a timer name or duration selector.")
        name = args.get("name")
        if name is not None:
            name = name.strip()
            if not name or not name.isprintable():
                return _failure("Give a short, non-empty timer name.")
        if self._clarification_required and action not in {"status", "list"}:
            return _failure("Please specify the timer's name or satellite in a new reply.")
        satellite = args.get("satellite")
        remote = (
            action == "stop" or args.get("scope") == "all_permitted"
            or satellite is not None and satellite.strip().casefold() not in {
                "here", "this satellite",
            }
        )
        if args.get("scope") == "all_permitted" and action != "cancel_all":
            return _failure(
                "Only an explicit cancel-all request supports all permitted satellites."
            )
        if args.get("scope") == "all_permitted" and not wide_scope_requested(auth.prepared.text):
            return _failure(
                "Cancel-all stays local unless this request explicitly says everywhere "
                "or all satellites. Otherwise name one satellite."
            )
        if remote:
            if self.remote_targets is None:
                return _failure("Cross-satellite or ringing-timer control is not available here.")
            return await self.remote_targets.async_control(self, args, llm_context)
        if (
            self.remote_targets is not None and self.remote_targets.source is not None
            and action in {"status", "list", "cancel", "cancel_all"}
        ):
            # Prefer the actual device list for alerts dismissed manually or
            # started outside this tool. Never treat the journal as ringing proof.
            if action in {"status", "list"}:
                return await self.remote_targets.async_local_query(self, args)
            return await self.remote_targets.async_control(
                self, {**args, "satellite": "here"}, llm_context,
            )
        # All awaits are above this fresh check. Native timer operations and
        # their ESPHome event callbacks are synchronous on this same event loop.
        if not self.available(hass) or (
            self.remaining_actions <= 0 and action not in {"status", "list"}
        ):
            return _failure("Timer control is not authorised.")
        journal = self._journal(hass)
        local = self._local_timers(journal)
        selector = start_duration if has_start else (None if adjusting else (
            duration if has_duration else None
        ))
        matches = [
            timer for timer in local
            if (name is None or (timer.name or "").strip().casefold() == name.casefold())
            and (selector is None or starting_seconds(timer) == selector)
        ]
        if action in {"status", "list"}:
            if action == "status" and (name is not None or selector is not None) and not matches:
                return _failure("I couldn't find a matching timer on this satellite.")
            return llm.ToolResult(data={
                "status": "query_answer",
                "timers": [{
                    "name": timer.name, "start_seconds": starting_seconds(timer),
                    "seconds_left": timer.seconds_left,
                    "state": (
                        "running" if timer.is_active else "paused"
                        if self._manager.timers.get(timer.id) is timer else "ended_unverified"
                    ),
                } for timer in matches[:MAX_TIMERS]],
            })
        if action == "cancel_all":
            if not local:
                return llm.ToolResult(data={"status": "query_answer", "timers": []})
            if len(local) > min(MAX_TIMERS, self.remaining_actions):
                return _failure("There are too many timers to cancel in one request.")
            if not all(self._claim("cancel", timer.id) for timer in local):
                return _failure("That timer request was already submitted; I haven't repeated it.")
            completed = 0
            dismissals = 0
            for timer in local:
                try:
                    # Callbacks can revoke a scope synchronously; recheck each effect.
                    if not self.available(hass):
                        raise ValueError("Source changed")
                    dismissals += self._cancel(timer, journal) == "dismissal_requested"
                    completed += 1
                    self.remaining_actions -= 1
                except Exception:
                    return llm.ToolResult(data={
                        "error": "I couldn't confirm all timer cancellations.",
                        "completed": completed,
                    }, error=True)
            return llm.ToolResult(data={
                "status": "accepted", "completed": completed,
                "timer_action": "cancelled_all", "dismissals": dismissals,
            })
        selected = None
        if action == "start":
            if len(local) >= MAX_TIMERS or len(journal) >= MAX_RETAINED:
                return _failure(
                    "There are too many retained timers. Cancel one before adding another."
                )
            claimed = self._claim("start", duration, name)
        else:
            if not matches:
                return _failure("I couldn't find a matching timer on this satellite.")
            if len(matches) != 1:
                self._clarification_required = True
                return llm.ToolResult(data={
                    "status": "clarification_required",
                    "message": (
                        "More than one timer matches here. Ask for its name or starting duration."
                    ),
                })
            selected = matches[0]
            if action != "cancel" and self._manager.timers.get(selected.id) is not selected:
                return _failure("That timer has ended; cancel or dismiss it instead.")
            if (
                adjusting and action == "add_time"
                and selected.seconds_left + duration > MAX_SECONDS
            ):
                return _failure("The resulting timer would exceed seven days.")
            claimed = self._claim(action, selected.id, duration if adjusting else None)
        if not claimed:
            return _failure("That timer request was already submitted; I haven't repeated it.")
        self.remaining_actions -= 1
        try:
            if action == "start":
                # Use Core's timer engine and existing ESPHome subscription, not
                # timer helpers, raw services, synthetic accounts or delayed commands.
                kwargs = {}
                if "context" in inspect.signature(self._manager.start_timer).parameters:
                    kwargs["context"] = auth.context
                timer_id = self._manager.start_timer(
                    self._identity[-1], args.get("hours"), args.get("minutes"),
                    args.get("seconds"), llm_context.language or hass.config.language,
                    name=name, **kwargs,
                )
                timer = self._manager.timers[timer_id]
                journal[timer_id] = _RetainedTimer(
                    self._identity, self._manager, self._handler, timer,
                )
                outcome = "started"
            else:
                timer = selected
                if action == "cancel":
                    outcome = self._cancel(timer, journal)
                elif action == "pause":
                    self._manager.pause_timer(timer.id)
                    outcome = "paused"
                elif action == "resume":
                    self._manager.unpause_timer(timer.id)
                    outcome = "resumed"
                else:
                    self._manager.add_time(
                        timer.id, duration if action == "add_time" else -duration,
                    )
                    outcome = "time_added" if action == "add_time" else "time_removed"
        except Exception:
            return _failure(
                "I couldn't confirm that timer request. "
                "It may have taken effect; check the satellite."
            )
        return llm.ToolResult(data={
            "status": "accepted", "completed": 1, "timer_action": outcome,
            "duration_seconds": timer.created_seconds, "name": timer.name,
            **({"adjustment_seconds": duration, "seconds_left": timer.seconds_left}
               if adjusting else {}),
        })


def starting_seconds(timer):
    """Original selector, not Core's expandable created_seconds progress-bar length."""
    return (
        (timer.start_hours or 0) * 3600 + (timer.start_minutes or 0) * 60
        + (timer.start_seconds or 0)
    )


def wide_scope_requested(text):
    """Conservative bulk-scope veto; a model flag or remembered 'yes' is not consent."""
    words = " ".join(re.findall(r"[a-z]+", str(text).casefold().replace("’", "'")))
    if re.search(r"\b(?:not|never|don t|dont|except|only|just)\b", words):
        return False
    return bool(re.search(
        r"\b(?:everywhere|(?:all|every) (?:the )?(?:permitted )?(?:satellites?|rooms?)"
        r"|(?:the )?(?:whole|entire) house)\b", words,
    ))


def spoken_duration(total):
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return ", ".join(
        f"{value} {unit}{'' if value == 1 else 's'}"
        for value, unit in ((hours, "hour"), (minutes, "minute"), (seconds, "second"))
        if value
    ) or "0 seconds"


def timer_acknowledgement(data):
    """Speak deterministic native results, without claiming physical alarm silence."""
    action = data.get("timer_action")
    name = data.get("name")
    label = f"the {name} timer" if name else "the timer"
    location = f" on {data['satellite']}" if data.get("satellite") else ""
    if action == "started":
        duration = spoken_duration(data["duration_seconds"])
        return f"Started {label} for {duration}."
    if action == "cancelled":
        return f"Cancelled {label}{location}."
    if action == "dismissal_requested":
        return f"Sent a dismissal request for {label}{location}."
    if action in {"paused", "resumed"}:
        return f"{action.capitalize()} {label}."
    if action in {"time_added", "time_removed"}:
        verb, direction = ("Added", "to") if action == "time_added" else ("Removed", "from")
        return f"{verb} {spoken_duration(data['adjustment_seconds'])} {direction} {label}."
    if action == "cancelled_all":
        dismissals = data.get("dismissals", 0)
        count = data["completed"] - dismissals
        parts = []
        if count:
            parts.append(f"Cancelled {count} timer{'' if count == 1 else 's'}{location}.")
        if dismissals:
            parts.append(
                f"Sent dismissal requests for {dismissals} ended timer "
                f"alert{'' if dismissals == 1 else 's'}{location}."
            )
        return " ".join(parts)
    return None
