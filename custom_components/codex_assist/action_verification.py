"""Read back only native action-result targets, without executing another action."""

from __future__ import annotations

import asyncio
import math
import re
from collections import Counter
from dataclasses import dataclass, replace

MAX_TARGETS = 16
VERIFY_TIMEOUT = 2.0
POLL_INTERVAL = 0.1
_ENTITY_ID = re.compile(r"[a-z_]+\.[a-z0-9_]+\Z")
_BINARY_DOMAINS = {"light", "switch", "fan", "humidifier", "input_boolean", "automation",
                   "remote", "siren"}
_OPERATIONS = {
    "HassTurnOn": "turn_on", "HassTurnOff": "turn_off", "HassToggle": "toggle",
    "HassOpenCover": "open", "HassCloseCover": "close",
    "HassLock": "lock", "HassUnlock": "unlock",
    "HassClimateSetTemperature": "set_temperature",
    "HassMediaPause": "pause", "HassMediaUnpause": "resume",
}


@dataclass(frozen=True)
class TargetEvidence:
    entity_id: str
    name: str
    domain: str
    operation: str
    command_result: str
    verification: str = "unconfirmed"
    reported_state: str | None = None
    expected_state: str | None = None
    reported_temperature: float | None = None
    requested_temperature: float | None = None
    temperature_unit: str | None = None

    def as_dict(self):
        # Identifiers are retained internally for exact readback, not spoken IDs.
        return {**{key: value for key, value in vars(self).items()
                   if key != "entity_id" and value is not None},
                "reply_status": self.reply_status}

    @property
    def reply_status(self):
        if self.command_result == "failed":
            return "failed"
        if self.verification in {"reported_requested_state", "reported_requested_setting"}:
            return "success"
        if self.verification == "not_observed":
            return "not_reached"
        return "unconfirmed"

    @property
    def speech(self):
        if self.command_result == "failed":
            return f"{self.name}: the command failed."
        if self.verification == "reported_requested_state":
            return {
                "on": f"I've turned {self.name} on.",
                "off": f"I've turned {self.name} off.",
                "open": f"I've opened {self.name}.",
                "closed": f"I've closed {self.name}.",
                "locked": f"I've locked {self.name}.",
                "unlocked": f"I've unlocked {self.name}.",
                "paused": f"I've paused {self.name}.",
                "playing": f"I've resumed {self.name}.",
            }.get(self.reported_state, f"{self.name}: the requested state is confirmed.")
        if self.verification == "reported_requested_setting":
            return (f"I've set {self.name}'s target temperature to "
                    f"{self.reported_temperature:g} {self.temperature_unit}.")
        observed = (f" It is still {self.reported_state}."
                    if self.verification == "not_observed" and self.reported_state else "")
        return (f"{self.name}: command accepted, but the requested result is not confirmed."
                f"{observed}")


def _text(value, limit=128):
    return (value if isinstance(value, str) and 0 < len(value) <= limit
            and value.isprintable() else None)


def _number(value):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and abs(value) < 1e6 else None)


def _native_tools(tools):
    from homeassistant.helpers import llm

    found = {}
    for tool in tools:
        underlying = tool
        for _ in range(3):
            if not hasattr(underlying, "tool"):
                break
            underlying = underlying.tool
        if isinstance(underlying, getattr(llm, "IntentTool", ())):
            intent_type = getattr(underlying, "intent_type", underlying.name)
            found[tool.name] = _OPERATIONS.get(intent_type, "other")
    return found


def _result_targets(contents, tools):
    """Only exact paired native action_done entity IDs, never model target guesses."""
    native = _native_tools(tools)
    calls = [call for item in contents if getattr(item, "role", None) == "assistant"
             for call in (getattr(item, "tool_calls", None) or ())
             if not getattr(call, "external", False)]
    if len({call.id for call in calls}) != len(calls):
        return []
    targets = []
    for call in calls:
        if call.tool_name not in native:
            continue
        results = [item for item in contents if getattr(item, "role", None) == "tool_result"
                   and getattr(item, "tool_call_id", None) == call.id]
        if len(results) != 1:
            continue
        wrapped = getattr(results[0], "result", None)
        data = wrapped.data if wrapped is not None else getattr(results[0], "tool_result", None)
        if (getattr(wrapped, "error", False) or not isinstance(data, dict)
                or data.get("response_type") != "action_done"):
            continue
        details = data.get("data")
        if (not isinstance(details, dict) or not isinstance(details.get("success"), list)
                or not isinstance(details.get("failed"), list)):
            continue
        for field, result in (("success", "accepted"), ("failed", "failed")):
            for target in details[field]:
                if not isinstance(target, dict) or target.get("type", "entity") != "entity":
                    continue
                entity_id = target.get("id")
                if (isinstance(entity_id, str) and len(entity_id) <= 255
                        and _ENTITY_ID.fullmatch(entity_id)):
                    targets.append((entity_id, native[call.tool_name], result,
                                    getattr(call, "tool_args", {})))
    # Multiple actions on one entity cannot safely share a final postcondition.
    duplicates = {eid for eid, count in Counter(t[0] for t in targets).items() if count > 1}
    return [(eid, "other" if eid in duplicates else operation, result, args)
            for eid, operation, result, args in targets]


def _expectation(state, operation, args):
    domain = state.entity_id.split(".", 1)[0]
    if domain in _BINARY_DOMAINS and operation in {"turn_on", "turn_off"}:
        return "on" if operation == "turn_on" else "off", None
    if domain == "lock" and operation in {"lock", "unlock", "turn_on", "turn_off"}:
        return "locked" if operation in {"lock", "turn_on"} else "unlocked", None
    if domain == "cover" and operation in {"open", "close", "turn_on", "turn_off"}:
        return "open" if operation in {"open", "turn_on"} else "closed", None
    if domain == "media_player" and operation in {"pause", "resume", "turn_off"}:
        return {"pause": "paused", "resume": "playing", "turn_off": "off"}[operation], None
    if domain == "climate" and operation == "turn_off":
        return "off", None
    if domain == "climate" and operation == "set_temperature":
        unit = state.attributes.get("temperature_unit")
        # Do not compare differently scaled values or infer a conversion here.
        if unit in {"°C", "°F"} and args.get("temperature_unit", unit) == unit:
            return None, _number(args.get("temperature"))
    return None, None


def _observe(state, evidence):
    observed = _text(state.state, 64)
    status = "unconfirmed"
    temperature = None
    if observed in {"unavailable", "unknown"}:
        status = "unavailable"
    elif state.attributes.get("assumed_state"):
        status = "optimistic_state"
    elif evidence.expected_state is not None:
        matches = observed == evidence.expected_state
        if evidence.domain == "cover" and "current_position" in state.attributes:
            matches = matches and state.attributes["current_position"] == (
                100 if evidence.expected_state == "open" else 0
            )
        status = "reported_requested_state" if matches else "not_observed"
    elif evidence.requested_temperature is not None:
        temperature = _number(state.attributes.get("temperature"))
        matches = (temperature is not None
                   and abs(temperature - evidence.requested_temperature) < 0.01
                   and state.attributes.get("temperature_unit") == evidence.temperature_unit)
        status = "reported_requested_setting" if matches else "not_observed"
    else:
        status = "no_verifiable_postcondition"
    return replace(evidence, verification=status, reported_state=observed,
                   reported_temperature=temperature)


async def async_verify_action(hass, outcome, contents, tools, context, *,
                              timeout=VERIFY_TIMEOUT, poll_interval=POLL_INTERVAL):
    """One total readback deadline; no refresh/service calls, retries or history lookups.

    Recheck current exposure and caller read permissions after each await. A matching
    state is a reported postcondition, not proof of a transition or physical feedback.
    """
    from homeassistant.auth.permissions.const import POLICY_READ
    from homeassistant.components.homeassistant.exposed_entities import async_should_expose
    from homeassistant.exceptions import HomeAssistantError

    if outcome.kind not in {"accepted", "partial", "failed"}:
        return outcome
    targets = _result_targets(contents, tools)
    if not targets:
        return outcome
    deadline = asyncio.get_running_loop().time() + max(0, min(timeout, VERIFY_TIMEOUT))
    reports = []
    expectations = {}
    withheld = len(targets) > MAX_TARGETS
    try:
        while True:
            reports = []
            user = None
            if user_id := getattr(context, "user_id", None):
                auth_timeout = max(0.001, deadline - asyncio.get_running_loop().time())
                async with asyncio.timeout(auth_timeout):
                    user = await hass.auth.async_get_user(user_id)
                if user is None or not user.is_active:
                    return outcome
            for entity_id, operation, command_result, args in targets[:MAX_TARGETS]:
                if (not async_should_expose(hass, "conversation", entity_id)
                        or (user is not None
                            and not user.permissions.check_entity(entity_id, POLICY_READ))):
                    withheld = True
                    continue
                state = hass.states.get(entity_id)
                if state is None:
                    withheld = True
                    continue
                domain = entity_id.split(".", 1)[0]
                expected, temperature, unit = expectations.setdefault(
                    entity_id, (*_expectation(state, operation, args),
                                state.attributes.get("temperature_unit")),
                )
                evidence = TargetEvidence(
                    entity_id, _text(state.name) or entity_id, domain, operation, command_result,
                    expected_state=expected, requested_temperature=temperature,
                    temperature_unit=unit if temperature is not None else None,
                )
                reports.append(_observe(state, evidence) if command_result == "accepted" else
                               replace(evidence, verification="command_failed"))
            pending = any(report.command_result == "accepted"
                          and (report.expected_state is not None
                               or report.requested_temperature is not None)
                          and report.verification not in {
                              "reported_requested_state", "reported_requested_setting",
                          } for report in reports)
            remaining = deadline - asyncio.get_running_loop().time()
            if not pending or remaining <= 0:
                break
            await asyncio.sleep(min(max(poll_interval, 0.01), remaining))
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, TimeoutError,
            OSError, HomeAssistantError):
        # A readback failure must not change the known execution result or replay it.
        return outcome
    return replace(outcome, targets=tuple(reports), target_details_withheld=withheld)
