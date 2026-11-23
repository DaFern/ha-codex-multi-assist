"""Optional paired RBAC tests: real admission/policy/timers, simulated audio provenance."""

import asyncio
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from homeassistant.core import Context

from custom_components.codex_assist.satellite_runtime import satellite_tools_supported

if not satellite_tools_supported():
    pytest.skip("Modern satellite tools required", allow_module_level=True)

pytest.importorskip("custom_components.ha_rbac.assist_policy")

from custom_components.ha_rbac.const import DATA_RBAC
from custom_components.ha_rbac.policy import Evaluator, default_roles
from custom_components.ha_rbac.satellite_admission import SatelliteAdmissionRegistry
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.components.intent.const import TIMER_DATA
from homeassistant.components.intent.timers import TimerManager
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist import (
    guest_control,
    guest_policy,
    satellite_timer_targets,
    speaker_packet,
)
from custom_components.codex_assist.codex_client import (
    CodexTextDelta,
    CodexToolCall,
    CodexToolCallDelta,
)
from custom_components.codex_assist.protected_model import async_fixed_tool_turn
from custom_components.codex_assist.rbac_satellite import ProtectedSatelliteDispatcher
from custom_components.codex_assist.satellite_timers import SatelliteTimerTool
from custom_components.codex_assist.timer_policy import async_timer_access, async_timer_access_batch
from custom_components.codex_assist.voice_match import SpeakerRuntime
from tests_ha.test_satellite_timer_targets import fleet as fleet
from tests_ha.test_satellite_timers import timers as timers


@pytest.fixture
async def admitted_timers(hass, monkeypatch):
    assert await async_setup_component(hass, "homeassistant", {})
    registry = er.async_get(hass)
    light = registry.async_get_or_create("light", "test", "timer-policy-light")
    hass.states.async_set(light.entity_id, "off", {"friendly_name": "Test light"})
    async_expose_entity(hass, "conversation", light.entity_id, True)
    entry = MockConfigEntry(domain="esphome")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("esphome", "paired-timer-satellite")},
    )
    satellite = registry.async_get_or_create(
        "assist_satellite", "esphome", "paired-timer-satellite",
        config_entry=entry, device_id=device.id,
    )
    hass.states.async_set(satellite.entity_id, "idle")
    store = SimpleNamespace(
        roles={**default_roles(), "guest": {
            "id": "guest", "name": "Test guest",
            "allow": {"entities": {"entity_ids": {
                light.entity_id: {"read": True, "control": True},
            }}},
        }},
        bindings={"speaker": ["guest"]}, global_deny={},
    )
    evaluator = Evaluator(hass, store)
    hass.data[DATA_RBAC] = SimpleNamespace(store=store, evaluator=evaluator)
    user = SimpleNamespace(
        id="speaker", is_active=True, is_owner=False, is_admin=False,
        system_generated=False, permissions=SimpleNamespace(check_entity=lambda *args: True),
    )

    async def get_user(uid):
        await asyncio.sleep(0)
        return user if uid == user.id else None

    monkeypatch.setattr(hass.auth, "async_get_user", get_user)
    state = SimpleNamespace(
        key=Fernet.generate_key().decode(), role="guest", online=True, held=[], events=[],
    )
    runtime = SpeakerRuntime()
    dispatcher = ProtectedSatelliteDispatcher(
        hass, runtime, key_provider=lambda: state.key, guest_role_provider=lambda: state.role,
        candidate_entity_ids=(light.entity_id,),
    )
    ingress = SatelliteAdmissionRegistry(
        hass, dispatcher, approved_satellite_ids=frozenset({satellite.entity_id}),
    )
    binding = ingress.register_transport(
        satellite.entity_id, state,
        connection_is_current=lambda actual: actual is state and state.online,
    )
    manager = TimerManager(hass)
    hass.data[TIMER_DATA] = manager
    manager.register_handler(
        device.id, lambda event, timer: state.events.append((event, timer.device_id)),
    )

    async def run(args, *, speaker=None, change=None, serialized=False):
        original = Context(user_id="unchanged-kiosk-caller")
        admission = binding.admit(original)
        wire = speaker_packet.encode(
            state.key, "Synthetic timer request",
            voice="profile" if speaker else None,
            revision="a" * 32 if speaker else None, ha_user_id=speaker,
        )
        text = runtime.handoffs.issue(state.key, wire)
        if serialized:
            text = str(text)

        async def handle(payload, context):
            assert context is original
            tool = next(t for t in payload["tools"] if t.name == SatelliteTimerTool.name)
            state.held.append(tool)
            if change is not None:
                change()
            result = await tool.async_call(
                hass, llm.ToolInput(tool_name=tool.name, tool_args=args),
                llm.LLMContext(
                    platform="codex_assist", context=context, language="en",
                    assistant="conversation", device_id=None,
                ),
            )
            return {"status": "denied" if result.error else "completed",
                    "completed": 0 if result.error else 1}

        result = await ingress.async_voice_turn(admission, transcript=text, handler=handle)
        assert original.user_id == "unchanged-kiosk-caller" or change is not None
        return result

    yield SimpleNamespace(
        run=run, manager=manager, state=state, store=store, evaluator=evaluator,
        user=user, device=device,
    )
    await ingress.async_close()
    runtime.handoffs.clear()
    for task in manager.timer_tasks.values():
        task.cancel()


@pytest.mark.parametrize("speaker", [None, "speaker"])
async def test_real_admission_start_and_cancel_across_fresh_turns(admitted_timers, speaker):
    e = admitted_timers
    assert await e.run(
        {"action": "start", "minutes": 10, "name": "Pasta"}, speaker=speaker,
    ) == {"status": "completed", "completed": 1}
    assert {t.device_id for t in e.manager.timers.values()} == {e.device.id}
    assert await e.run(
        {"action": "cancel", "name": "Pasta"}, speaker=speaker,
    ) == {"status": "completed", "completed": 1}
    assert not e.manager.timers
    assert len(e.state.events) == 2
    assert not e.state.held[0].available(e.manager.hass)


@pytest.mark.parametrize("change", ["disconnect", "key", "role", "read_permission", "account"])
async def test_real_policy_or_source_revocation_prevents_timer_effect(admitted_timers, change):
    e = admitted_timers

    def revoke():
        if change == "disconnect":
            e.state.online = False
        elif change == "key":
            e.state.key = Fernet.generate_key().decode()
        elif change == "role":
            e.state.role = "removed"
        elif change == "account":
            e.user.is_active = False
        else:
            e.store.roles["guest"]["allow"] = {}
            e.evaluator.invalidate()

    result = await e.run(
        {"action": "start", "seconds": 10},
        speaker="speaker" if change == "account" else None, change=revoke,
    )
    assert result["status"] == "denied"
    assert not e.manager.timers
    assert not e.state.events


async def test_serialized_transcript_never_exposes_timer_tool(admitted_timers):
    e = admitted_timers
    result = await e.run({"action": "start", "seconds": 5}, serialized=True)
    assert result["status"] == "denied"
    assert not e.state.held
    assert not e.manager.timers


@pytest.fixture
async def paired_fleet(hass, fleet, monkeypatch):
    """Pair real private admissions, native/RBAC checks and model loop with fake device RPC."""
    f = fleet
    assert await async_setup_component(hass, "homeassistant", {})
    registry = er.async_get(hass)
    light = registry.async_get_or_create(
        "light", "test", "paired-fleet-light", suggested_object_id="test_timer",
    )
    assert light.entity_id == f.e.ids[0]
    hass.states.async_set(light.entity_id, "off", {"friendly_name": "Test light"})
    ids = [light.entity_id, *f.state.enrolled]
    for eid in ids:
        async_expose_entity(hass, "conversation", eid, True)
    store = SimpleNamespace(
        roles={**default_roles(), "guest": {
            "id": "guest", "name": "Guest", "allow": {"entities": {"entity_ids": {
                eid: {"read": True, "control": True} for eid in ids
            }}},
        }},
        bindings={"speaker": ["guest"]}, global_deny={},
    )
    evaluator = Evaluator(hass, store)
    hass.data[DATA_RBAC] = SimpleNamespace(store=store, evaluator=evaluator)
    user = SimpleNamespace(
        id="speaker", is_active=True, is_owner=False, is_admin=False, system_generated=False,
        permissions=SimpleNamespace(check_entity=lambda *args: True),
    )

    async def get_user(uid):
        await asyncio.sleep(0)
        return user if uid == "speaker" else None

    monkeypatch.setattr(hass.auth, "async_get_user", get_user)
    monkeypatch.setattr(guest_control, "async_guest_snapshot", guest_policy.async_guest_snapshot)
    monkeypatch.setattr(
        guest_control, "async_check_guest_action", guest_policy.async_check_guest_action,
    )
    monkeypatch.setattr(satellite_timer_targets, "async_timer_access", async_timer_access)
    monkeypatch.setattr(
        satellite_timer_targets, "async_timer_access_batch", async_timer_access_batch,
    )
    key = Fernet.generate_key().decode()
    runtime = SpeakerRuntime()
    dispatcher = ProtectedSatelliteDispatcher(
        hass, runtime, key_provider=lambda: key, guest_role_provider=lambda: "guest",
        candidate_entity_ids=f.e.ids, timer_satellites_provider=lambda: f.state.enrolled,
    )
    ingress = SatelliteAdmissionRegistry(
        hass, dispatcher, approved_satellite_ids=frozenset(f.state.enrolled),
    )
    binding = ingress.register_transport(
        f.kitchen, f.state, connection_is_current=lambda actual: actual is f.state,
    )
    profile = SimpleNamespace(
        model="synthetic", reasoning_effort="low", reasoning_summary="auto", text_verbosity="low",
    )
    seen = []

    async def run(args, *, speaker=None, mutation=None):
        admission = binding.admit(f.e.context)
        wire = speaker_packet.encode(
            key, "Stop the timer that is going off",
            voice="profile" if speaker else None, revision="a" * 32 if speaker else None,
            ha_user_id=speaker,
        )
        text = runtime.handoffs.issue(key, wire)
        replies = []

        async def handle(payload, context):
            class Client:
                async def stream_turn(self, **kwargs):
                    seen.append(kwargs)
                    if kwargs["input_items"][-1].get("type") == "function_call_output":
                        yield CodexTextDelta("Which timer did you mean?")
                        return
                    if mutation:
                        mutation()
                    yield CodexToolCallDelta(CodexToolCall(
                        "cancel", SatelliteTimerTool.name, args,
                    ))

            result, speech = await async_fixed_tool_turn(
                hass, Client(), profile, payload, context, text, "en",
            )
            replies.append(speech)
            return result

        result = await ingress.async_voice_turn(admission, transcript=text, handler=handle)
        return result, replies

    yield SimpleNamespace(
        fleet=f, run=run, store=store, evaluator=evaluator, seen=seen,
    )
    await ingress.async_close()
    runtime.handoffs.clear()


@pytest.mark.parametrize("speaker", [None, "speaker"])
async def test_paired_model_stops_unique_other_satellite_alert(paired_fleet, speaker):
    p = paired_fleet
    ringing = p.fleet.start(p.fleet.office, finished=True)
    running = p.fleet.start(p.fleet.kitchen, name="Pasta")
    result, replies = await p.run({"action": "stop"}, speaker=speaker)
    assert result == {"status": "completed", "completed": 1}
    assert replies == ["Cancelled the Tea timer on Office screen."]
    assert ringing not in p.fleet.state.satellites[p.fleet.office].cli.rows
    assert set(p.fleet.e.manager.timers) == {running}


async def test_paired_read_only_other_satellite_is_not_a_cancellation_grant(paired_fleet):
    p = paired_fleet
    ringing = p.fleet.start(p.fleet.office, finished=True)
    p.store.roles["guest"]["allow"]["entities"]["entity_ids"][p.fleet.office]["control"] = False
    p.evaluator.invalidate()
    result, _ = await p.run({"action": "stop"})
    assert result["status"] == "denied"
    assert ringing in p.fleet.state.satellites[p.fleet.office].cli.rows
    assert not any(name == "vs_cancel_timer" for _, name, _ in p.fleet.state.calls)


async def test_paired_permission_revocation_after_model_prompt_stops_remote_effect(paired_fleet):
    p = paired_fleet
    ringing = p.fleet.start(p.fleet.office, finished=True)

    def revoke():
        p.store.roles["guest"]["allow"]["entities"]["entity_ids"].pop(p.fleet.office)
        p.evaluator.invalidate()

    result, _ = await p.run({"action": "stop"}, mutation=revoke)
    assert result["status"] == "denied"
    assert ringing in p.fleet.state.satellites[p.fleet.office].cli.rows
    assert not any(name == "vs_cancel_timer" for _, name, _ in p.fleet.state.calls)
