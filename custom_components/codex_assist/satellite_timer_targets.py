"""Enrolled, permission-filtered Kiosk timer discovery and exact alert cancellation.

Only the native ESPHome vs_list_timers/vs_cancel_timer actions are usable here.
Service objects come from the exact live runtime, never a guessed service name.
No LAN discovery, remote-admin URL, shared-timer protocol or generic action bridge.
"""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass

from homeassistant.core import ServiceCall
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm

from .satellite_timers import MAX_SECONDS, MAX_TIMERS, _failure, _identity
from .timer_policy import async_timer_access, async_timer_access_batch


def _component(hass):
    # Do not pull optional speech/audio dependencies into timer-only factory tests
    # or installations where Assist satellite has never been set up.
    if "assist_satellite" not in hass.data:
        return None
    from homeassistant.components.assist_satellite.const import DATA_COMPONENT

    return hass.data.get(DATA_COMPONENT)


def _commands(runtime):
    from aioesphomeapi import SupportsResponseType, UserServiceArgType

    wanted = {"vs_list_timers": {}, "vs_cancel_timer": {"timer_id": UserServiceArgType.STRING}}
    result = {}
    for service in runtime.services.values():
        if service.name not in wanted:
            continue
        if (
            service.name in result or type(service.key) is not int
            or {arg.name: arg.type for arg in service.args} != wanted[service.name]
            or len(service.args) != len(wanted[service.name])
            or service.supports_response not in {
                SupportsResponseType.OPTIONAL, SupportsResponseType.ONLY,
            }
        ):
            return None
        result[service.name] = service
    return result if set(result) == set(wanted) else None


def _text(value, limit=128):
    return type(value) is str and 0 < len(value) <= limit and value.isprintable()


@dataclass
class TimerTarget:
    entity_id: str
    identity: tuple
    entity: object
    runtime: object
    handler: object
    commands: dict
    label: str
    aliases: tuple

    def alive(self, hass):
        try:
            entry = er.async_get(hass).async_get(self.entity_id)
            config = hass.config_entries.async_get_entry(self.identity[-2])
            component = _component(hass)
            from homeassistant.components.intent.const import TIMER_DATA

            manager = hass.data.get(TIMER_DATA)
            return bool(
                _identity(entry) == self.identity and config is not None
                and config.runtime_data is self.runtime and self.runtime.available
                and component is not None and component.get_entity(self.entity_id) is self.entity
                and self.entity.available and self.entity.cli is self.runtime.client
                and self.entity.config_entry is config
                and self.runtime.client.is_connected and bool(self.runtime.client.noise_psk)
                and manager is not None
                and manager.handlers.get(self.identity[-1]) == self.handler
                and getattr(self.handler, "__self__", None) is self.entity
                and _commands(self.runtime) == self.commands
            )
        except Exception:
            return False

    def fingerprint(self):
        return hashlib.sha256(json.dumps([
            self.entity_id, self.identity, self.label, sorted(self.aliases),
            [(name, service.key) for name, service in sorted(self.commands.items())],
        ], ensure_ascii=True).encode()).hexdigest()

    async def query(self, hass, context):
        data = await self._call(hass, context, "vs_list_timers", {})
        if type(data) is not dict or set(data) != {"timers"}:
            raise ValueError("Unsupported timer response")
        rows = data["timers"]
        if type(rows) is not list or len(rows) > MAX_TIMERS:
            raise ValueError("Unsupported timer response")
        result, seen = [], set()
        for row in rows:
            if (
                type(row) is not dict
                or not {"timer_id", "name", "total_seconds", "seconds_left",
                        "is_active", "finished"} <= set(row)
                or not set(row) <= {"timer_id", "name", "total_seconds", "seconds_left",
                                    "is_active", "finished", "ends_at"}
                or not _text(row["timer_id"]) or row["timer_id"] in seen
                or type(row["name"]) is not str or len(row["name"]) > 80
                or row["name"] and not row["name"].isprintable()
                or any(type(row[key]) is not int or not 0 <= row[key] <= MAX_SECONDS
                       for key in ("total_seconds", "seconds_left"))
                or row["total_seconds"] == 0
                or type(row["is_active"]) is not bool or type(row["finished"]) is not bool
                or row["finished"] and (row["is_active"] or row["seconds_left"] != 0)
            ):
                raise ValueError("Unsupported timer response")
            from homeassistant.components.intent.const import TIMER_DATA

            manager = hass.data.get(TIMER_DATA)
            native = manager.timers.get(row["timer_id"]) if manager else None
            if native is not None and (
                native.device_id != self.identity[-1] or native.conversation_command
                or row["finished"]
            ):
                raise ValueError("Timer ownership or lifecycle disagrees")
            seen.add(row["timer_id"])
            result.append({key: row[key] for key in (
                "timer_id", "name", "total_seconds", "seconds_left", "is_active", "finished",
            )})
        return result

    async def dismiss(self, hass, context, timer_id):
        # Never send an empty ID: firmware's "only timer" fallback is not authority.
        if not _text(timer_id):
            raise ValueError("Missing exact timer")
        await self._call(hass, context, "vs_cancel_timer", {"timer_id": timer_id})

    async def _call(self, hass, context, name, data):
        from homeassistant.components.esphome.manager import execute_service

        if not self.alive(hass) or name not in {"vs_list_timers", "vs_cancel_timer"}:
            raise ValueError("Timer target changed")
        service = self.commands[name]
        call = ServiceCall(
            hass=hass, domain="esphome", service=name, data=data,
            context=context, return_response=True,
        )
        async with asyncio.timeout(5):
            result = await execute_service(
                self.runtime, service, call, supports_response=service.supports_response,
            )
        if not self.alive(hass):
            raise ValueError("Timer target changed")
        return result


def _binding(hass, eid, *, local=False):
    try:
        entry = er.async_get(hass).async_get(eid)
        identity = _identity(entry)
        component = _component(hass)
        config = hass.config_entries.async_get_entry(identity[-2]) if identity else None
        entity = component.get_entity(eid) if component else None
        if config is None or entity is None:
            return None
        runtime = config.runtime_data
        commands = _commands(runtime)
        from homeassistant.components.intent.const import TIMER_DATA

        manager = hass.data.get(TIMER_DATA)
        handler = manager.handlers.get(identity[-1]) if manager else None
        if commands is None or not callable(handler):
            return None
        # Remote metadata is read only after the timer oracle permits every field.
        aliases = {eid}
        label = "this satellite"
        if not local:
            state = hass.states.get(eid)
            label = entry.name or entry.original_name or (state.name if state else eid)
            if not _text(label):
                return None
            aliases.update(value for value in sorted(entry.aliases)[:8] if _text(value))
            aliases.add(label)
            area = ar.async_get(hass).async_get_area(entry.area_id or (
                entity.device_entry.area_id if getattr(entity, "device_entry", None) else None
            ))
            # Registry device inheritance is used even when the entity lacks device_entry.
            if area is None:
                from homeassistant.helpers import device_registry as dr

                device = dr.async_get(hass).async_get(identity[-1])
                area = ar.async_get(hass).async_get_area(
                    dr.async_get_effective_area_id(hass, device) if device else None,
                )
            if area:
                aliases.add(area.name)
                aliases.update(value for value in sorted(area.aliases)[:8] if _text(value))
        target = TimerTarget(
            eid, identity, entity, runtime, handler, commands, label, tuple(sorted(aliases)),
        )
        return target if target.alive(hass) else None
    except Exception:
        return None


class TimerTargets:
    """Request-bound catalogue; its whole visibility participates in saved dialogue."""

    def __init__(self, hass, auth, enrolled, current_enrollment):
        self.hass, self.auth = hass, auth
        self.enrolled, self.current_enrollment = enrolled, current_enrollment
        self.targets = {}
        self.unobserved = ()
        self.source = _binding(hass, auth.satellite_id, local=True)

    @classmethod
    async def async_create(cls, hass, auth, enrolled, current_enrollment):
        if (
            type(enrolled) is not tuple or not 0 < len(enrolled) <= 32
            or any(type(eid) is not str or not eid.startswith("assist_satellite.")
                   for eid in enrolled)
            or len(set(enrolled)) != len(enrolled) or auth.satellite_id not in enrolled
            or not callable(current_enrollment)
        ):
            return None
        self = cls(hass, auth, tuple(sorted(enrolled)), current_enrollment)
        self.targets, self.unobserved = await self._permitted()
        if self.targets and not await async_timer_access_batch(
            hass, auth, tuple(sorted(self.targets)),
        ):
            return None
        fresh = {eid: _binding(hass, eid) for eid in self.targets}
        if any(target is None for target in fresh.values()):
            return None
        self.targets = fresh
        return self if self.auth.valid() else None

    async def _permitted(self):
        result = {}
        unobserved = []
        for eid in self.enrolled:
            if await async_timer_access(self.hass, self.auth, eid):
                target = _binding(self.hass, eid)
                if target:
                    result[eid] = target
                else:
                    unobserved.append(eid)
        return result, tuple(sorted(unobserved))

    @property
    def view(self):
        return sorted([
            *(target.fingerprint() for target in self.targets.values()),
            *(hashlib.sha256(json.dumps(["timer_unobserved", eid]).encode()).hexdigest()
              for eid in self.unobserved),
        ])

    @property
    def catalogue(self):
        return [{
            "satellite": target.label, "aliases": list(target.aliases),
        } for target in self.targets.values()]

    async def current(self):
        try:
            if (
                not self.auth.valid()
                or tuple(sorted(self.current_enrollment())) != self.enrolled
                or self.source is not None and not self.source.alive(self.hass)
            ):
                return False
            current, unobserved = await self._permitted()
            if set(current) != set(self.targets) or unobserved != self.unobserved:
                return False
            if self.targets and not await async_timer_access_batch(
                self.hass, self.auth, tuple(sorted(self.targets)),
            ):
                return False
            # Resolve metadata synchronously after the last permission await.
            fresh = [_binding(self.hass, eid) for eid in self.targets]
            return (
                self.auth.valid()
                and all(t is not None for t in fresh)
                and sorted(t.fingerprint() for t in fresh)
                == sorted(t.fingerprint() for t in self.targets.values())
                and (self.source is None or self.source.alive(self.hass))
                and all(t.alive(self.hass) for t in self.targets.values())
            )
        except Exception:
            return False

    async def _allowed(self, tool, target, action):
        if (
            not tool.available(self.hass) or not target.alive(self.hass)
            or not await tool.validate_references()
        ):
            return False
        allowed = (
            True if target is self.source else await async_timer_access(
                self.hass, self.auth, target.entity_id, action=action,
            )
        )
        return allowed and tool.available(self.hass) and target.alive(self.hass)

    def _resolve(self, name):
        if name is not None and name.strip().casefold() in {"here", "this satellite"}:
            return [self.source] if self.source else []
        if name is None:
            return []
        return [
            target for target in self.targets.values()
            if name.strip().casefold() in {value.casefold() for value in target.aliases}
        ]

    async def async_local_query(self, tool, args):
        if self.source is None or not await self._allowed(tool, self.source, "read"):
            return _failure("The satellite's live timer list is unavailable.")
        try:
            rows = await self.source.query(self.hass, self.auth.context)
            if not await self._allowed(tool, self.source, "read"):
                return _failure("Timer control is not authorised.")
        except Exception:
            return _failure("I couldn't read the satellite's live timer list.")
        return llm.ToolResult(data={
            "status": "query_answer",
            "timers": [{
                "name": row["name"] or None, "start_seconds": row["total_seconds"],
                "seconds_left": row["seconds_left"],
                "state": "alerting" if row["finished"] else (
                    "running" if row["is_active"] else "paused"
                ),
            } for row in _matching(rows, args)],
        })

    async def async_control(self, tool, args, llm_context):
        action, name = args["action"], args.get("satellite")
        if action not in {"cancel", "stop", "cancel_all"}:
            return _failure("Only timer cancellation can target another satellite.")
        if name is not None and args.get("scope") == "all_permitted":
            return _failure("Name one satellite or explicitly choose all permitted satellites.")
        if name is None and (
            action == "stop" or args.get("scope") == "all_permitted"
        ):
            if self.source is None:
                return _failure("I can't check this satellite's alerts. Please name the satellite.")
            for eid in self.unobserved:
                if await async_timer_access(self.hass, self.auth, eid, action=action):
                    return _failure(
                        "An authorised satellite cannot report its timer alerts. "
                        "Please name the satellite."
                    )
        if name is not None:
            selected = self._resolve(name)
            if len(selected) != 1:
                return _clarify("Which permitted satellite did you mean?", tool)
            target = selected[0]
            aliases = (
                ("here", "this satellite", target.entity_id)
                if target is self.source else target.aliases
            )
            if (target is not self.source or action == "stop") and not mentioned(
                aliases, self.auth.prepared.text,
            ):
                return _failure("Please name the target satellite in this request.")
        elif action == "cancel" or action == "cancel_all" and args.get("scope") != "all_permitted":
            selected = [self.source] if self.source else []
        else:
            selected = list(self.targets.values())
            if self.source is not None:
                selected = [
                    t for t in selected if t.entity_id != self.source.entity_id
                ] + [self.source]
        if not selected:
            return _failure(
                "No permitted satellite with a live timer-list capability is available."
            )
        if action == "stop" or any(target is not self.source for target in selected):
            if args.get("name") and not mentioned((args["name"],), self.auth.prepared.text):
                return _failure("Please specify the timer's name in this request.")
            if any(key in args for key in (
                "hours", "minutes", "seconds", "start_hours", "start_minutes", "start_seconds",
            )) and not re.search(
                r"\b(?:hours?|minutes?|seconds?)\b", self.auth.prepared.text.casefold(),
            ):
                return _failure("Please specify the timer's starting duration or name.")
        matches = []
        for target in selected:
            if not await self._allowed(tool, target, action):
                if name is not None:
                    return _failure("Timer cancellation is not permitted on that satellite.")
                continue
            try:
                rows = await target.query(self.hass, self.auth.context)
                if not await self._allowed(tool, target, action):
                    return _failure("Timer authority changed while checking the satellites.")
            except Exception:
                return _failure("I couldn't check all timer alerts. Please name the satellite.")
            for row in _matching(rows, args):
                if action != "stop" or row["finished"]:
                    matches.append((target, row))
        if not matches:
            if action == "cancel_all":
                return llm.ToolResult(data={"status": "query_answer", "timers": []})
            return _failure(
                "I couldn't find an active timer alert." if action == "stop"
                else "I couldn't find a matching timer on the permitted satellites."
            )
        if action != "cancel_all" and len(matches) != 1:
            return _clarify(
                "More than one timer matches. Ask for its satellite, name or duration.", tool,
            )
        if len(matches) > min(MAX_TIMERS, tool.remaining_actions):
            return _failure("There are too many timers to cancel in one request.")
        completed, last = 0, None
        for target, row in matches:
            if not await self._allowed(tool, target, action):
                return _partial(completed)
            if not tool._claim("cancel_remote", row["timer_id"], target.entity_id):
                return _partial(completed)
            from homeassistant.components.intent.const import TIMER_DATA

            manager = self.hass.data.get(TIMER_DATA)
            timer = manager.timers.get(row["timer_id"]) if manager else None
            if timer is not None and (
                timer.device_id != target.identity[-1] or timer.conversation_command
            ):
                return _partial(completed)
            try:
                if timer is not None and not row["finished"]:
                    # Exact Core ID, never the firmware's name/duration/global fallback.
                    manager.cancel_timer(timer.id)
                    outcome = "cancelled"
                elif row["finished"] and timer is None:
                    await target.dismiss(self.hass, self.auth.context, row["timer_id"])
                    outcome = "dismissal_requested"
                else:
                    return _partial(completed)
                completed += 1
                tool.remaining_actions -= 1
                last = {
                    "name": row["name"] or None, "satellite": target.label,
                    "timer_action": outcome,
                }
                # A successful RPC is admission, not proof the alert disappeared.
                if row["finished"]:
                    if not await self._allowed(tool, target, action):
                        return _partial(completed)
                    after = await target.query(self.hass, self.auth.context)
                    if not await self._allowed(tool, target, action):
                        return _partial(completed)
                    if any(r["timer_id"] == row["timer_id"] for r in after):
                        return _partial(completed)
                    last["timer_action"] = "cancelled"
            except Exception:
                return _partial(completed)
        if action == "cancel_all":
            last = {"timer_action": "cancelled_all", "satellite": (
                "the permitted satellites" if args.get("scope") == "all_permitted"
                else selected[0].label
            )}
        return llm.ToolResult(data={"status": "accepted", "completed": completed, **last})


def _matching(rows, args):
    selector = None
    prefix = "start_" if any("start_" + key in args for key in (
        "hours", "minutes", "seconds",
    )) else ""
    if any(prefix + key in args for key in ("hours", "minutes", "seconds")):
        selector = sum(args.get(prefix + key, 0) * unit for key, unit in (
            ("hours", 3600), ("minutes", 60), ("seconds", 1),
        ))
    name = args.get("name")
    return [
        row for row in rows
        if (name is None or row["name"].strip().casefold() == name.strip().casefold())
        and (selector is None or row["total_seconds"] == selector)
    ]


def mentioned(aliases, text):
    """Exact declared aliases in this turn, never a model-chosen or remembered destination."""
    def words(value):
        return " ".join(re.findall(r"\w+", value.casefold().replace("_", " ")))

    utterance = " " + words(str(text)) + " "
    return any(
        (normalised := words(alias)) and " " + normalised + " " in utterance
        for alias in aliases
    )


def _clarify(message, tool):
    tool._clarification_required = True
    return llm.ToolResult(data={"status": "clarification_required", "message": message})


def _partial(completed):
    return llm.ToolResult(data={
        "error": "I couldn't confirm the timer cancellations. Check the named satellite.",
        "completed": completed,
    }, error=True)
