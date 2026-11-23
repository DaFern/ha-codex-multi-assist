"""Bounded read-only checks and failure-only speech, never detached control."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

from .action_control import ActionOutcome
from .action_verification import TargetEvidence, _expectation, _observe

DATA_FOLLOWUPS = "codex_assist_device_followups"


def cancel_native_followup(hass, device_id):
    """A newer turn invalidates failure speech from an earlier turn."""
    if not device_id:
        return
    pending = hass.data.get(DATA_FOLLOWUPS, {})
    task = pending.pop(device_id, None)
    if task is not None:
        task.cancel()


def schedule_native_followup(hass, entry, device_id, context, observe, reply):
    """Only the originating registered satellite can receive a delayed spoken error.

    Text/phone conversations have no reliable second speech channel. Do not invent
    a destination, announce elsewhere or create an unsolicited phone notification.
    """
    from homeassistant.helpers import entity_registry as er

    if not device_id or not context.user_id or "assist_satellite" not in hass.data:
        return
    component = hass.data["assist_satellite"]
    registry = er.async_get(hass)
    matches = [
        entity for entity in er.async_entries_for_device(registry, device_id)
        if entity.domain == "assist_satellite" and entity.device_id == device_id
        and entity.disabled_by is None
    ]
    if len(matches) != 1:
        return
    identity = matches[0]
    satellite = component.get_entity(identity.entity_id)
    if satellite is None:
        return
    options = entry.options
    pending = hass.data.setdefault(DATA_FOLLOWUPS, {})
    cancel_native_followup(hass, device_id)

    def current():
        return (
            entry.options is options and satellite.available
            and registry.async_get(identity.entity_id) is identity
            and component.get_entity(identity.entity_id) is satellite
            and pending.get(device_id) is asyncio.current_task()
        )

    async def announce(text):
        await satellite.async_internal_announce(message=text, preannounce=False)

    async def run():
        try:
            await async_failure_followup(
                observe=observe, reply=reply, current=current,
                ready=lambda: satellite.state == "idle", announce=announce,
            )
        finally:
            if pending.get(device_id) is asyncio.current_task():
                pending.pop(device_id, None)

    task = pending[device_id] = entry.async_create_background_task(
        hass, run(), "codex-native-device-failure-followup", eager_start=False,
    )

    def completed(done):
        if pending.get(device_id) is done:
            pending.pop(device_id, None)

    task.add_done_callback(completed)


class DeviceChecks:
    """Exact accepted targets; no tool objects or executable authorisation retained."""

    def __init__(self):
        self.targets = {}

    def add(self, hass, entity_ids, action, args):
        from homeassistant.helpers import entity_registry as er

        if type(entity_ids) not in {list, tuple} or len(entity_ids) > 32:
            return
        for eid in entity_ids:
            if type(eid) is not str or "." not in eid:
                continue
            # A second action on the same target has no single safe postcondition.
            if eid in self.targets:
                self.targets[eid] = None
                continue
            identity = er.async_get(hass).async_get(eid)
            if identity is not None:
                self.targets[eid] = (identity, action, dict(args))

    async def observe(self, hass, read, *, timeout=2.0):
        """Fresh projected reads only; missing permission/identity suppresses details."""
        from homeassistant.helpers import entity_registry as er

        ids = tuple(eid for eid, plan in self.targets.items() if plan is not None)
        if not ids:
            return None
        deadline = asyncio.get_running_loop().time() + timeout
        reports = []
        while True:
            rows = await read(ids)
            if rows is None or {row["entity_id"] for row in rows} != set(ids):
                return None
            reports = []
            for row in rows:
                eid = row["entity_id"]
                identity, action, args = self.targets[eid]
                if er.async_get(hass).async_get(eid) is not identity or "name" not in row:
                    return None
                operation = {
                    "open_blind": "open", "close_blind": "close", "power_on": "turn_on",
                    "power_off": "turn_off",
                }.get(action, action)
                state = SimpleNamespace(
                    entity_id=eid, state=row["state"], attributes=row["attributes"],
                )
                expected, temperature = _expectation(state, operation, args)
                evidence = TargetEvidence(
                    eid, row["name"], eid.partition(".")[0], operation, "accepted",
                    expected_state=expected, requested_temperature=temperature,
                    temperature_unit=row["attributes"].get("temperature_unit"),
                )
                reports.append(_observe(state, evidence))
            pending = any(
                report.verification == "not_observed" for report in reports
            )
            remaining = deadline - asyncio.get_running_loop().time()
            if not pending or remaining <= 0:
                break
            await asyncio.sleep(min(0.1, remaining))
        # Unsupported postconditions (scripts, seek, etc.) aren't failure evidence.
        failures = tuple(report for report in reports if report.verification in {
            "not_observed", "unavailable", "optimistic_state",
        })
        return failure_only(ActionOutcome("accepted", targets=failures))


def failure_only(outcome):
    """Suppress normal responses; never turn absent telemetry into proven failure."""
    if outcome.kind in {"failed", "partial"}:
        return outcome
    failures = tuple(target for target in outcome.targets if target.reply_status != "success"
                     and target.verification != "no_verifiable_postcondition"
                     and not (target.domain == "cover" and target.reported_state in {
                         "opening", "closing",
                     }))
    return replace(outcome, kind="unconfirmed", targets=failures) if failures else None


async def async_failure_followup(*, observe, reply, current, ready, announce, timeout=25.0):
    """Wait off the response path; recheck after every await and before speaking.

    A newer turn, unload, disconnect, changed policy or changed target drops the
    follow-up. No background tool calls, retries or saved execution grants.
    """
    try:
        async with asyncio.timeout(timeout):
            if not current():
                return
            failure = await observe()
            if failure is None or not current():
                return
            # Let the acknowledgement finish and never cancel an active pipeline.
            while current() and not ready():
                await asyncio.sleep(0.1)
            if not current():
                return
            # Feedback may have arrived during TTS or the follow-up listening window.
            failure = await observe()
            if failure is None or not current() or not ready():
                return
            text = await reply(failure)
            if not current() or not ready():
                return
            fresh = await observe()
            if fresh != failure or not current() or not ready():
                return
            await announce(text)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Reporting failure must never cause a replay or an unguarded announcement.
        return
