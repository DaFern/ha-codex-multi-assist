"""Read-only device feedback and guarded background speech with native registries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import Context
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist.action_control import ActionOutcome
from custom_components.codex_assist.action_followup import (
    DeviceChecks,
    async_failure_followup,
    cancel_native_followup,
    failure_only,
    schedule_native_followup,
)
from custom_components.codex_assist.action_verification import TargetEvidence


@pytest.fixture
def observed(hass):
    entity = er.async_get(hass).async_get_or_create("light", "test", "feedback")
    hass.states.async_set(entity.entity_id, "off", {"friendly_name": "Test lamp"})
    checks = DeviceChecks()
    checks.add(hass, [entity.entity_id], "turn_on", {})
    state = SimpleNamespace(allowed=True)

    async def read(ids):
        if not state.allowed:
            return None
        return [{
            "entity_id": eid, "state": hass.states.get(eid).state, "name": "Test lamp",
            "attributes": dict(hass.states.get(eid).attributes),
        } for eid in ids]

    return SimpleNamespace(entity=entity, checks=checks, state=state, read=read)


async def test_matching_feedback_is_silent_and_mismatching_feedback_is_uncertain(hass, observed):
    e = observed
    outcome = await e.checks.observe(hass, e.read, timeout=0)
    assert outcome.kind == "unconfirmed"
    assert outcome.targets[0].name == "Test lamp"
    assert outcome.targets[0].verification == "not_observed"
    hass.states.async_set(e.entity.entity_id, "on")
    assert await e.checks.observe(hass, e.read, timeout=0) is None


async def test_permission_revocation_or_missing_projection_suppresses_private_details(
    hass, observed,
):
    observed.state.allowed = False
    assert await observed.checks.observe(hass, observed.read, timeout=0) is None


async def test_changed_registry_identity_suppresses_old_request(hass, observed):
    er.async_get(hass).async_update_entity(observed.entity.entity_id, name="Changed identity")
    assert await observed.checks.observe(hass, observed.read, timeout=0) is None


async def test_duplicate_actions_have_no_invented_final_postcondition(hass, observed):
    e = observed
    e.checks.add(hass, [e.entity.entity_id], "turn_off", {})
    assert await e.checks.observe(hass, e.read, timeout=0) is None


async def test_unsupported_postcondition_is_not_reported_as_device_failure(hass, observed):
    e = observed
    e.checks = DeviceChecks()
    e.checks.add(hass, [e.entity.entity_id], "shuffle", {})
    assert await e.checks.observe(hass, e.read, timeout=0) is None


@pytest.mark.parametrize("state", ["unavailable", "unknown"])
async def test_unavailable_feedback_gets_uncertainty_not_a_physical_failure_claim(
    hass, observed, state,
):
    hass.states.async_set(observed.entity.entity_id, state)
    outcome = await observed.checks.observe(hass, observed.read, timeout=0)
    assert outcome.kind == "unconfirmed"
    assert outcome.targets[0].verification == "unavailable"


async def test_successful_feedback_never_generates_or_speaks_another_reply():
    reply, announce = AsyncMock(), AsyncMock()
    await async_failure_followup(
        observe=AsyncMock(return_value=None), reply=reply,
        current=lambda: True, ready=lambda: True, announce=announce,
    )
    reply.assert_not_awaited()
    announce.assert_not_awaited()


@pytest.mark.parametrize("revoke_at", ["none", "observe", "reply", "fresh"])
async def test_failures_speak_only_after_current_permission_and_fresh_feedback(revoke_at):
    target = TargetEvidence("light.test", "Test lamp", "light", "turn_on", "accepted",
                            verification="not_observed", reported_state="off")
    failure = ActionOutcome("unconfirmed", targets=(target,))
    state = SimpleNamespace(current=True, reads=0)
    spoken = []

    async def observe():
        state.reads += 1
        if revoke_at == "observe" or revoke_at == "fresh" and state.reads == 3:
            state.current = False
        return failure

    async def reply(outcome):
        assert outcome is failure
        if revoke_at == "reply":
            state.current = False
        return "Test lamp hasn't responded, sir."

    async def announce(text):
        spoken.append(text)

    await async_failure_followup(
        observe=observe, reply=reply, current=lambda: state.current,
        ready=lambda: True, announce=announce,
    )
    assert spoken == (["Test lamp hasn't responded, sir."] if revoke_at == "none" else [])


async def test_late_feedback_after_receipt_playback_suppresses_obsolete_failure():
    failure = ActionOutcome("unconfirmed")
    checks = iter([failure, None])
    reply, announce = AsyncMock(), AsyncMock()

    async def observe():
        return next(checks)

    await async_failure_followup(
        observe=observe, reply=reply, current=lambda: True,
        ready=lambda: True, announce=announce,
    )
    reply.assert_not_awaited()
    announce.assert_not_awaited()


async def test_busy_satellite_is_never_interrupted_and_work_expires():
    announce = AsyncMock()
    await async_failure_followup(
        observe=AsyncMock(return_value=ActionOutcome("unconfirmed")),
        reply=AsyncMock(), current=lambda: True, ready=lambda: False,
        announce=announce, timeout=0.01,
    )
    announce.assert_not_awaited()


async def test_background_cancellation_is_not_swallowed():
    observe = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await async_failure_followup(
            observe=observe, reply=AsyncMock(), current=lambda: True,
            ready=lambda: True, announce=AsyncMock(),
        )


async def test_failure_filter_does_not_turn_unsupported_telemetry_into_failure():
    target = TargetEvidence("script.test", "Test script", "script", "other", "accepted",
                            verification="no_verifiable_postcondition")
    assert failure_only(ActionOutcome("accepted", targets=(target,))) is None


@pytest.fixture
def native_channel(hass):
    entry = MockConfigEntry(domain="codex_assist")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("test", "origin")},
    )
    identity = er.async_get(hass).async_get_or_create(
        "assist_satellite", "test", "origin", config_entry=entry, device_id=device.id,
    )
    satellite = SimpleNamespace(
        available=True, state="idle", async_internal_announce=AsyncMock(),
    )
    hass.data["assist_satellite"] = SimpleNamespace(
        get_entity=lambda eid: satellite if eid == identity.entity_id else None,
    )
    return SimpleNamespace(entry=entry, device=device, satellite=satellite, identity=identity)


async def test_native_followup_is_lifecycle_owned_and_speaks_only_to_original_satellite(
    hass, native_channel,
):
    from custom_components.codex_assist.action_followup import DATA_FOLLOWUPS

    c = native_channel
    failure = ActionOutcome("unconfirmed")
    schedule_native_followup(
        hass, c.entry, c.device.id, Context(user_id="original-subject"),
        AsyncMock(return_value=failure), AsyncMock(return_value="No response, sir."),
    )
    task = hass.data[DATA_FOLLOWUPS][c.device.id]
    assert task in c.entry._background_tasks
    await task
    c.satellite.async_internal_announce.assert_awaited_once_with(
        message="No response, sir.", preannounce=False,
    )
    assert not hass.data[DATA_FOLLOWUPS]


async def test_new_turn_cancels_pending_native_failure_speech(hass, native_channel):
    from custom_components.codex_assist.action_followup import DATA_FOLLOWUPS

    c = native_channel
    schedule_native_followup(
        hass, c.entry, c.device.id, Context(user_id="original-subject"),
        AsyncMock(return_value=ActionOutcome("unconfirmed")), AsyncMock(),
    )
    task = hass.data[DATA_FOLLOWUPS][c.device.id]
    cancel_native_followup(hass, c.device.id)
    await asyncio.gather(task, return_exceptions=True)
    c.satellite.async_internal_announce.assert_not_awaited()
    assert not hass.data[DATA_FOLLOWUPS]


async def test_no_source_channel_is_not_permission_to_announce_elsewhere(hass, native_channel):
    observe = AsyncMock()
    schedule_native_followup(
        hass, native_channel.entry, None, Context(user_id="subject"), observe, AsyncMock(),
    )
    observe.assert_not_awaited()
    native_channel.satellite.async_internal_announce.assert_not_awaited()


async def test_protected_followup_uses_pinned_transport_not_expired_execution_scope(
    hass, native_channel, monkeypatch,
):
    import sys
    from types import ModuleType

    # These optional external audio dependencies are unrelated to the scheduler.
    for name, attr in (("pymicro_vad", "MicroVad"), ("pyspeex_noise", "AudioProcessor")):
        if name not in sys.modules:
            module = ModuleType(name)
            setattr(module, attr, lambda *args, **kwargs: None)
            monkeypatch.setitem(sys.modules, name, module)
    from custom_components.codex_assist.kiosk_adapter import KioskSatelliteAdapter

    c = native_channel
    adapter = object.__new__(KioskSatelliteAdapter)
    adapter.hass, adapter.entry = hass, c.entry
    adapter._options, adapter._closed = c.entry.options, False
    adapter._followups, adapter._tasks = {}, {}
    connection = SimpleNamespace(is_connected=True)
    c.satellite.entity_id = c.identity.entity_id
    c.satellite.cli = SimpleNamespace(_connection=connection)
    adapter._bindings = {c.identity.entity_id: (connection, object())}
    adapter._connection_checks = {c.identity.entity_id: lambda actual: actual is connection}
    adapter._entity = lambda eid: c.satellite
    read = AsyncMock()
    checks = SimpleNamespace(
        targets={"light.test": "observational-only"},
        observe=AsyncMock(return_value=ActionOutcome("unconfirmed")),
    )
    adapter._start_followup(
        c.satellite, connection, SimpleNamespace(pending_speech=False),
        {"device_checks": checks, "followup_read": read,
         "failure_reply": AsyncMock(return_value="Test lamp is not responding, sir.")},
    )
    await adapter._followups[c.identity.entity_id]
    c.satellite.async_internal_announce.assert_awaited_once_with(
        message="Test lamp is not responding, sir.", preannounce=False,
    )
    assert checks.observe.await_count == 3


@pytest.mark.parametrize("matched", [False, True])
async def test_protected_observer_has_fresh_projection_only_and_revokes_with_role_or_key(
    hass, monkeypatch, matched,
):
    import hashlib

    from custom_components.codex_assist import guest_policy
    from custom_components.codex_assist.rbac_satellite import ProtectedSatelliteDispatcher

    state = SimpleNamespace(role="guest", key="synthetic-test-key")
    rows = [{"entity_id": "light.test", "state": "off", "attributes": {}}]
    snapshot = AsyncMock(return_value=rows)
    monkeypatch.setattr(
        guest_policy, "async_speaker_snapshot" if matched else "async_guest_snapshot", snapshot,
    )
    dispatcher = SimpleNamespace(
        hass=hass, _closed=False, _key_provider=lambda: state.key,
        _guest_role_provider=lambda: state.role,
    )
    subject = "speaker" if matched else "guest"
    read = ProtectedSatelliteDispatcher._followup_reader(
        dispatcher, subject, matched, ("light.test",),
        hashlib.sha256(state.key.encode()).digest(),
    )
    assert await read(("light.test",)) is rows
    snapshot.assert_awaited_once_with(hass, subject, ("light.test",))
    assert await read(("light.not_a_candidate",)) is None
    snapshot.reset_mock()
    if matched:
        state.key = "changed-synthetic-test-key"
    else:
        state.role = "different-guest"
    assert await read(("light.test",)) is None
    snapshot.assert_not_awaited()
