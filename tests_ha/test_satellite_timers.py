"""Real Core timers/registries, simulated admission and satellite event delivery."""

import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import Context

from custom_components.codex_assist.satellite_runtime import satellite_tools_supported

if not satellite_tools_supported():
    pytest.skip("Satellite tools require modern native tool types", allow_module_level=True)

import probatio
from homeassistant.components.intent.const import TIMER_DATA
from homeassistant.components.intent.timers import TimerEventType, TimerManager
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist.guest_control import (
    GuestAuthorization,
    MatchedAuthorization,
    async_guest_tools,
)
from custom_components.codex_assist.satellite_timers import (
    DATA_TIMERS,
    FINISHED_RETENTION_SECONDS,
    MAX_SECONDS,
    SatelliteTimerTool,
)
from custom_components.codex_assist.voice_match import PreparedRequest


@pytest.fixture
def timers(hass, monkeypatch):
    from custom_components.codex_assist import guest_control, guest_policy

    monkeypatch.setattr(guest_policy, "capabilities_supported", lambda: False)
    monkeypatch.setattr(guest_control, "capabilities_supported", lambda: False)
    monkeypatch.setattr(guest_policy, "async_voice_references", AsyncMock(return_value=[]))
    monkeypatch.setattr(guest_control, "async_check_guest_action", AsyncMock(return_value=True))
    projection = [{"entity_id": "light.test_timer", "name": "Test light",
                   "state": "off", "attributes": {}}]
    monkeypatch.setattr(guest_control, "async_guest_snapshot", AsyncMock(return_value=projection))
    entry = MockConfigEntry(domain="esphome")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("esphome", "test-timer-satellite")},
    )
    satellite = er.async_get(hass).async_get_or_create(
        "assist_satellite", "esphome", "test-timer-satellite",
        config_entry=entry, device_id=device.id,
    )
    hass.states.async_set(satellite.entity_id, "idle")
    manager = TimerManager(hass)
    hass.data[TIMER_DATA] = manager
    events = []

    def handler(event, timer):
        events.append((event, timer.id, timer.device_id, timer.seconds_left))

    manager.register_handler(device.id, handler)
    state = SimpleNamespace(current=True, role="guest")
    context = Context(user_id="original-timer-caller")
    prepared = PreparedRequest("Set a timer", "", None, None, verified=True)
    auth = GuestAuthorization(
        context, prepared, "guest", satellite.entity_id,
        request_is_current=lambda ctx, req: state.current and ctx is context and req is prepared,
        selected_role=lambda: state.role,
    )
    env = SimpleNamespace(
        manager=manager, events=events, device=device, satellite=satellite,
        state=state, auth=auth, context=context, prepared=prepared,
        policy=AsyncMock(return_value=True), ids=("light.test_timer",),
    )
    yield env
    for task in manager.timer_tasks.values():
        task.cancel()


def context(env, **kwargs):
    return llm.LLMContext(
        platform="codex_assist", context=kwargs.get("context", env.context),
        assistant=kwargs.get("assistant", "conversation"),
        language="en", device_id=kwargs.get("device_id"),
    )


async def invoke(hass, env, args, *, tool=None, llm_context=None):
    tool = tool or SatelliteTimerTool(hass, env.auth)
    if tool.validate_references is None:
        tool.validate_references = env.policy
    return await tool.async_call(
        hass, llm.ToolInput(tool_name=tool.name, tool_args=args),
        llm_context or context(env),
    )


async def test_native_start_then_cancel_on_a_fresh_turn(hass, timers):
    e = timers
    result = await invoke(hass, e, {"action": "start", "minutes": 10, "name": "Pasta"})
    assert not result.error
    assert result.data == {
        "status": "accepted", "completed": 1, "timer_action": "started",
        "duration_seconds": 600, "name": "Pasta",
    }
    timer = next(iter(e.manager.timers.values()))
    assert timer.device_id == e.device.id
    assert timer.conversation_command is None
    if hasattr(timer, "context"):
        assert timer.context is e.context
    assert e.events == [(TimerEventType.STARTED, timer.id, e.device.id, 600)]
    result = await invoke(hass, e, {"action": "cancel", "name": " pasta "})
    assert result.data["timer_action"] == "cancelled"
    assert not e.manager.timers
    assert e.events[-1] == (TimerEventType.CANCELLED, timer.id, e.device.id, 0)
    assert hass.data[DATA_TIMERS] == {}


async def test_factory_adds_timer_with_live_full_policy_validator(hass, timers):
    payload = await async_guest_tools(hass, timers.auth, timers.ids)
    tool = next(t for t in payload["tools"] if t.name == SatelliteTimerTool.name)
    assert tool.validate_references is payload["validate"]
    assert await payload["validate"]()
    result = await invoke(
        hass, timers, {"action": "start", "seconds": 30}, tool=tool,
    )
    assert not result.error


async def test_matched_speaker_keeps_original_context(hass, timers):
    e = timers
    prepared = replace(e.prepared, voice="test-speaker", ha_user_id="matched-account")
    e.auth = MatchedAuthorization(
        e.context, prepared, "matched-account", e.satellite.entity_id,
        request_is_current=lambda ctx, req: e.state.current and req is prepared,
        expires=time.monotonic() + 30,
    )
    assert not (await invoke(hass, e, {"action": "start", "seconds": 5})).error
    assert e.context.user_id == "original-timer-caller"


@pytest.mark.parametrize("change", [
    "disconnect", "role", "caller", "expired", "unverified", "foreign_context",
    "wrong_assistant", "registry_device", "disabled", "handler", "manager", "no_handler",
])
async def test_changed_authority_or_native_identity_has_no_timer_effect(hass, timers, change):
    e = timers
    tool = SatelliteTimerTool(hass, e.auth)
    ctx = context(e)
    if change == "disconnect":
        e.state.current = False
    elif change == "role":
        e.state.role = "changed"
    elif change == "caller":
        e.context.user_id = "changed"
    elif change in {"expired", "unverified"}:
        tool._auth = (
            replace(e.auth, expires=0) if change == "expired"
            else replace(e.auth, prepared=replace(e.prepared, verified=False))
        )
    elif change == "foreign_context":
        ctx = context(e, context=Context(user_id=e.context.user_id))
    elif change == "wrong_assistant":
        ctx = context(e, assistant="other")
    elif change == "registry_device":
        er.async_get(hass).async_update_entity(e.satellite.entity_id, device_id=None)
    elif change == "disabled":
        er.async_get(hass).async_update_entity(
            e.satellite.entity_id, disabled_by=er.RegistryEntryDisabler.USER,
        )
    elif change == "handler":
        e.manager.handlers[e.device.id] = lambda *args: None
    elif change == "manager":
        hass.data[TIMER_DATA] = TimerManager(hass)
    else:
        e.manager.handlers.pop(e.device.id)
    result = await invoke(
        hass, e, {"action": "start", "minutes": 10}, tool=tool, llm_context=ctx,
    )
    assert result.error
    assert e.events == []
    assert e.manager.timers == {}
    assert DATA_TIMERS not in hass.data


async def test_revocation_during_reference_check_denies_start_and_cancel(hass, timers):
    e = timers
    await invoke(hass, e, {"action": "start", "minutes": 10})
    tool = SatelliteTimerTool(hass, e.auth)

    async def revoke():
        e.state.current = False
        return True

    tool.validate_references = revoke
    assert (await invoke(hass, e, {"action": "cancel"}, tool=tool)).error
    assert len(e.manager.timers) == 1
    assert len(e.events) == 1
    assert (await invoke(hass, e, {"action": "start", "seconds": 1}, tool=tool)).error


@pytest.mark.parametrize("args", [
    {"action": "start"},
    {"action": "start", "seconds": 0},
    {"action": "start", "hours": 168, "seconds": 1},
    {"action": "start", "seconds": True},
    {"action": "start", "seconds": 1, "name": " "},
    {"action": "start", "seconds": 1, "name": "a\nb"},
    {"action": "cancel", "seconds": 0},
])
async def test_invalid_duration_and_names_never_create_timers(hass, timers, args):
    result = await invoke(hass, timers, args)
    assert result.error
    assert timers.events == []


@pytest.mark.parametrize("extra", [
    {"conversation_command": "turn on something"},
    {"device_id": "another-device"}, {"area": "another-room"},
    {"timer_id": "another-timer"}, {"entity_id": "timer.helper"},
])
async def test_model_cannot_add_delayed_commands_or_choose_a_different_target(hass, timers, extra):
    with pytest.raises(probatio.Invalid):
        await invoke(hass, timers, {"action": "start", "seconds": 1, **extra})
    assert timers.events == []


@pytest.mark.parametrize("selector", [{}, {"name": "Foreign"}, {"minutes": 4}])
async def test_cancel_never_falls_back_to_other_satellite_or_delayed_command(
    hass, timers, selector,
):
    e = timers
    e.manager.register_handler("foreign-device", lambda *args: None)
    other_id = e.manager.start_timer("foreign-device", None, 4, None, "en", name="Foreign")
    delayed_id = e.manager.start_timer(
        e.device.id, None, 4, None, "en", name="Foreign",
        conversation_command="not a countdown",
    )
    result = await invoke(hass, e, {"action": "cancel", **selector})
    assert result.error
    assert set(e.manager.timers) == {other_id, delayed_id}
    assert e.events == []


async def test_multiple_matches_require_clarification_before_cancel(hass, timers):
    e = timers
    for name in ("Tea", "Pasta"):
        await invoke(hass, e, {"action": "start", "minutes": 10, "name": name})
    result = await invoke(hass, e, {"action": "cancel"})
    assert result.data["status"] == "clarification_required"
    assert len(e.manager.timers) == 2
    result = await invoke(hass, e, {"action": "cancel", "name": "Tea"})
    assert not result.error
    assert {timer.name for timer in e.manager.timers.values()} == {"Pasta"}
    assert not (await invoke(hass, e, {"action": "cancel"})).error


async def test_duplicate_names_can_be_selected_by_starting_duration(hass, timers):
    for minutes in (5, 10):
        await invoke(hass, timers, {"action": "start", "minutes": minutes, "name": "Tea"})
    assert (await invoke(hass, timers, {"action": "cancel", "name": "Tea"})).data[
        "status"
    ] == "clarification_required"
    result = await invoke(hass, timers, {"action": "cancel", "minutes": 10, "name": "Tea"})
    assert not result.error
    assert [t.created_seconds for t in timers.manager.timers.values()] == [300]


async def test_finished_timer_can_request_native_dismissal_without_global_handler_patch(
    hass, timers,
):
    e = timers
    await invoke(hass, e, {"action": "start", "seconds": 1, "name": "Egg"})
    timer_id = next(iter(e.manager.timers))
    original_handler = e.manager.handlers[e.device.id]
    e.manager.timer_tasks[timer_id].cancel()
    e.manager._timer_finished(timer_id)
    assert not e.manager.timers
    assert e.events[-1][0] == TimerEventType.FINISHED
    result = await invoke(hass, e, {"action": "cancel", "name": "Egg"})
    assert result.data["timer_action"] == "dismissal_requested"
    assert e.events[-1] == (TimerEventType.CANCELLED, timer_id, e.device.id, 0)
    assert e.manager.handlers[e.device.id] is original_handler
    assert (await invoke(hass, e, {"action": "cancel", "name": "Egg"})).error


async def test_finished_timer_record_expires_and_does_not_follow_a_replacement_handler(
    hass, timers,
):
    await invoke(hass, timers, {"action": "start", "seconds": 1})
    timer = next(iter(timers.manager.timers.values()))
    timers.manager.timer_tasks[timer.id].cancel()
    timers.manager._timer_finished(timer.id)
    timer.updated_at -= (FINISHED_RETENTION_SECONDS + 1) * 1_000_000_000
    assert (await invoke(hass, timers, {"action": "cancel"})).error
    assert hass.data[DATA_TIMERS] == {}
    await invoke(hass, timers, {"action": "start", "seconds": 2})
    timer = next(iter(timers.manager.timers.values()))
    timers.manager.timer_tasks[timer.id].cancel()
    timers.manager._timer_finished(timer.id)
    timers.manager.handlers[timers.device.id] = lambda *args: None
    assert (await invoke(hass, timers, {"action": "cancel"})).error


async def test_per_turn_replay_and_budget_never_repeat_a_start(hass, timers):
    tool = SatelliteTimerTool(hass, timers.auth)
    args = {"action": "start", "seconds": 60}
    assert not (await invoke(hass, timers, args, tool=tool)).error
    assert (await invoke(hass, timers, args, tool=tool)).error
    assert len(timers.manager.timers) == 1
    tool.remaining_actions = 0
    assert (await invoke(hass, timers, {"action": "cancel"}, tool=tool)).error


async def test_shared_effect_ledger_denial_never_starts_timer(hass, timers):
    tool = SatelliteTimerTool(hass, timers.auth)
    tool.claim_effect = lambda *args: False
    assert (await invoke(
        hass, timers, {"action": "start", "seconds": 1}, tool=tool,
    )).error
    assert timers.events == []


async def test_callback_failure_is_unconfirmed_and_not_retried(hass, timers):
    def broken(event, timer):
        raise RuntimeError("simulated transport failure")

    timers.manager.handlers[timers.device.id] = broken
    tool = SatelliteTimerTool(hass, timers.auth)
    args = {"action": "start", "seconds": 1}
    result = await invoke(hass, timers, args, tool=tool)
    assert result.error
    assert "may have taken effect" in result.data["error"]
    assert len(timers.manager.timers) == 1
    assert (await invoke(hass, timers, args, tool=tool)).error
    assert len(timers.manager.timers) == 1


async def test_factory_omits_timer_tool_for_devices_without_timer_subscription(hass, timers):
    timers.manager.handlers.clear()
    payload = await async_guest_tools(hass, timers.auth, timers.ids)
    assert SatelliteTimerTool.name not in {tool.name for tool in payload["tools"]}


async def test_policy_revocation_is_checked_before_timer_effect(hass, timers, monkeypatch):
    from custom_components.codex_assist import guest_control

    payload = await async_guest_tools(hass, timers.auth, timers.ids)
    tool = next(t for t in payload["tools"] if t.name == SatelliteTimerTool.name)
    monkeypatch.setattr(
        guest_control, "async_check_guest_action", AsyncMock(return_value=False),
    )
    assert (await invoke(hass, timers, {"action": "start", "seconds": 5}, tool=tool)).error
    assert timers.events == []


async def test_no_projection_or_policy_validator_cannot_enable_timers(hass, timers, monkeypatch):
    from custom_components.codex_assist import guest_control

    monkeypatch.setattr(guest_control, "async_guest_snapshot", AsyncMock(return_value=[]))
    payload = await async_guest_tools(hass, timers.auth, timers.ids)
    assert payload["tools"] == []
    tool = SatelliteTimerTool(hass, timers.auth)
    result = await tool.async_call(
        hass, llm.ToolInput(tool_name=tool.name, tool_args={"action": "start", "seconds": 5}),
        context(timers),
    )
    assert result.error
    assert timers.events == []


async def test_native_accepted_results_get_specific_spoken_acknowledgements(hass, timers):
    from custom_components.codex_assist.codex_client import CodexToolCall, CodexToolCallDelta
    from custom_components.codex_assist.protected_model import async_fixed_tool_turn

    e = timers
    profile = SimpleNamespace(
        model="synthetic", reasoning_effort="low", reasoning_summary="auto", text_verbosity="low",
    )
    for action, expected in (
        ("start", "Started the Tea timer for 10 minutes."),
        ("cancel", "Cancelled the Tea timer."),
    ):
        tool = SatelliteTimerTool(hass, e.auth)
        tool.validate_references = e.policy
        client = SimpleNamespace()

        async def stream_turn(*, _tool=tool, _action=action, **kwargs):
            assert "satellite_timer" in kwargs["instructions"]
            yield CodexToolCallDelta(CodexToolCall(
                "test-call", _tool.name, {"action": _action, "minutes": 10, "name": "Tea"},
            ))

        client.stream_turn = stream_turn
        payload = {
            "tools": [tool], "prompt": "Synthetic permitted context",
            "validate": AsyncMock(return_value=True),
        }
        result, speech = await async_fixed_tool_turn(
            hass, client, profile, payload, e.context, f"{action} a timer", "en",
        )
        assert result == {"status": "completed", "completed": 1}
        assert speech == expected
    assert MAX_SECONDS == 604800


async def test_untrusted_llm_device_context_cannot_redirect_the_timer(hass, timers):
    result = await invoke(
        hass, timers, {"action": "start", "seconds": 3},
        llm_context=context(timers, device_id="foreign-device"),
    )
    assert not result.error
    assert {timer.device_id for timer in timers.manager.timers.values()} == {timers.device.id}


async def test_capacity_limit_does_not_cancel_or_start_anything(hass, timers, monkeypatch):
    from custom_components.codex_assist import satellite_timers

    monkeypatch.setattr(satellite_timers, "MAX_TIMERS", 1)
    assert not (await invoke(hass, timers, {"action": "start", "seconds": 1})).error
    result = await invoke(hass, timers, {"action": "start", "seconds": 2})
    assert result.error
    assert len(timers.events) == 1
    assert len(timers.manager.timers) == 1


async def test_dismissal_acknowledgement_does_not_claim_physical_silence():
    from custom_components.codex_assist.satellite_timers import timer_acknowledgement

    assert timer_acknowledgement({
        "timer_action": "dismissal_requested", "name": None,
    }) == "Sent a dismissal request for the timer."


async def test_ambiguous_timer_result_gets_a_question_instead_of_generic_success(hass, timers):
    from custom_components.codex_assist.codex_client import (
        CodexTextDelta,
        CodexToolCall,
        CodexToolCallDelta,
    )
    from custom_components.codex_assist.protected_model import async_fixed_tool_turn

    for name in ("Tea", "Pasta"):
        await invoke(hass, timers, {"action": "start", "minutes": 10, "name": name})
    rounds = []

    class Client:
        async def stream_turn(self, **kwargs):
            rounds.append(kwargs)
            if len(rounds) == 1:
                yield CodexToolCallDelta(CodexToolCall(
                    "cancel", SatelliteTimerTool.name, {"action": "cancel"},
                ))
            else:
                assert "clarification_required" in kwargs["input_items"][-1]["output"]
                yield CodexTextDelta("Which timer: tea or pasta?")

    tool = SatelliteTimerTool(hass, timers.auth)
    tool.validate_references = timers.policy
    result, speech = await async_fixed_tool_turn(
        hass, Client(), SimpleNamespace(
            model="synthetic", reasoning_effort="low", reasoning_summary="auto",
            text_verbosity="low",
        ),
        {"tools": [tool], "prompt": "Synthetic"},
        timers.context, "Cancel my timer", "en",
    )
    assert result == {"status": "completed", "completed": 0}
    assert speech == "Which timer: tea or pasta?"
    assert len(timers.manager.timers) == 2


async def test_list_and_status_return_real_remaining_time_and_pause_state(hass, timers):
    assert (await invoke(hass, timers, {"action": "list"})).data["timers"] == []
    await invoke(hass, timers, {"action": "start", "minutes": 10, "name": "Pasta"})
    timer = next(iter(timers.manager.timers.values()))
    timer.updated_at -= 30 * 1_000_000_000
    result = await invoke(hass, timers, {"action": "status", "name": "Pasta"})
    assert result.data["timers"] == [{
        "name": "Pasta", "start_seconds": 600, "seconds_left": 570, "state": "running",
    }]
    await invoke(hass, timers, {"action": "pause", "name": "Pasta"})
    assert not timer.is_active
    assert timer.seconds_left == 570
    assert (await invoke(hass, timers, {"action": "status"})).data["timers"][0]["state"] == "paused"
    await invoke(hass, timers, {"action": "resume", "name": "Pasta"})
    assert timer.is_active
    assert [event[0] for event in timers.events] == [
        TimerEventType.STARTED, TimerEventType.UPDATED, TimerEventType.UPDATED,
    ]


async def test_add_remove_use_separate_starting_duration_selector(hass, timers):
    for minutes in (5, 10):
        await invoke(hass, timers, {"action": "start", "minutes": minutes, "name": "Tea"})
    before = {timer.id: timer.seconds_left for timer in timers.manager.timers.values()}
    ambiguous = await invoke(hass, timers, {"action": "add_time", "minutes": 2, "name": "Tea"})
    assert ambiguous.data["status"] == "clarification_required"
    assert {timer.id: timer.seconds_left for timer in timers.manager.timers.values()} == before
    result = await invoke(hass, timers, {
        "action": "add_time", "minutes": 2, "start_minutes": 10, "name": "Tea",
    })
    assert result.data["seconds_left"] == 720
    assert result.data["adjustment_seconds"] == 120
    # Original duration remains the selector even after Core expands created_seconds.
    result = await invoke(hass, timers, {
        "action": "remove_time", "seconds": 30, "start_minutes": 10, "name": "Tea",
    })
    assert result.data["seconds_left"] == 690
    assert sorted(timer.seconds_left for timer in timers.manager.timers.values()) == [300, 690]


async def test_adjust_paused_timer_without_resuming_it(hass, timers):
    await invoke(hass, timers, {"action": "start", "minutes": 10})
    await invoke(hass, timers, {"action": "pause"})
    await invoke(hass, timers, {"action": "add_time", "minutes": 2})
    timer = next(iter(timers.manager.timers.values()))
    assert not timer.is_active
    assert timer.seconds_left == 720
    await invoke(hass, timers, {"action": "remove_time", "minutes": 20})
    assert timer.seconds_left == 0
    assert not timer.is_active


@pytest.mark.parametrize("action", ["pause", "resume", "add_time", "remove_time"])
async def test_ended_timer_cannot_be_resurrected_or_adjusted(hass, timers, action):
    await invoke(hass, timers, {"action": "start", "seconds": 2})
    timer_id = next(iter(timers.manager.timers))
    timers.manager.timer_tasks[timer_id].cancel()
    timers.manager._timer_finished(timer_id)
    result = await invoke(hass, timers, {"action": action, **(
        {"seconds": 1} if action in {"add_time", "remove_time"} else {}
    )})
    assert result.error
    assert not timers.manager.timers
    assert len(timers.events) == 2


async def test_local_cancel_all_excludes_foreign_timers_and_delayed_commands(hass, timers):
    for name in ("Tea", "Pasta"):
        await invoke(hass, timers, {"action": "start", "minutes": 10, "name": name})
    timers.manager.register_handler("foreign", lambda *args: None)
    other = timers.manager.start_timer("foreign", None, 10, None, "en")
    delayed = timers.manager.start_timer(
        timers.device.id, None, 10, None, "en", conversation_command="test delayed command",
    )
    result = await invoke(hass, timers, {"action": "cancel_all"})
    assert result.data == {
        "status": "accepted", "completed": 2, "timer_action": "cancelled_all", "dismissals": 0,
    }
    assert set(timers.manager.timers) == {other, delayed}


async def test_local_cancel_all_reports_partial_callback_failure(hass, timers):
    for name in ("Tea", "Pasta"):
        await invoke(hass, timers, {"action": "start", "minutes": 10, "name": name})
    original = timers.manager.handlers[timers.device.id]
    calls = []

    def handler(event, timer):
        calls.append(event)
        if len(calls) == 2:
            raise RuntimeError("Synthetic send failure")
        original(event, timer)

    timers.manager.handlers[timers.device.id] = handler
    result = await invoke(hass, timers, {"action": "cancel_all"})
    assert result.error
    assert result.data["completed"] == 1
    assert len(calls) == 2


@pytest.mark.parametrize("args", [
    {"action": "add_time"}, {"action": "remove_time"},
    {"action": "add_time", "seconds": 0},
    {"action": "add_time", "seconds": True},
    {"action": "cancel_all", "name": "Tea"},
    {"action": "cancel_all", "minutes": 1},
    {"action": "start", "minutes": 1, "start_minutes": 2},
    {"action": "status", "scope": "all_permitted"},
    {"action": "pause", "satellite": "somewhere else"},
])
async def test_invalid_remaining_controls_never_change_timers(hass, timers, args):
    await invoke(hass, timers, {"action": "start", "minutes": 10})
    result = await invoke(hass, timers, args)
    assert result.error
    assert len(timers.events) == 1


async def test_add_time_never_exceeds_duration_cap(hass, timers):
    await invoke(hass, timers, {"action": "start", "hours": 168})
    assert (await invoke(hass, timers, {"action": "add_time", "minutes": 1})).error
    assert len(timers.events) == 1


@pytest.mark.parametrize(("data", "expected"), [
    ({"timer_action": "paused", "name": "Tea"}, "Paused the Tea timer."),
    ({"timer_action": "resumed", "name": None}, "Resumed the timer."),
    ({"timer_action": "time_added", "name": "Tea", "adjustment_seconds": 120},
     "Added 2 minutes to the Tea timer."),
    ({"timer_action": "time_removed", "name": None, "adjustment_seconds": 30},
     "Removed 30 seconds from the timer."),
    ({"timer_action": "cancelled_all", "completed": 2}, "Cancelled 2 timers."),
])
async def test_remaining_controls_have_specific_acknowledgements(data, expected):
    from custom_components.codex_assist.satellite_timers import timer_acknowledgement

    assert timer_acknowledgement(data) == expected


@pytest.mark.parametrize(("text", "expected"), [
    ("Cancel all timers", False), ("Cancel all timers in the kitchen", False),
    ("Yes", False), ("Cancel all timers everywhere", True),
    ("Cancel every timer in the whole house", True),
    ("Cancel timers on all permitted satellites", True),
    ("Cancel all timers except the kitchen", False),
    ("Don't cancel all timers everywhere", False),
])
async def test_wider_scope_requires_this_turns_explicit_request(text, expected):
    from custom_components.codex_assist.satellite_timers import wide_scope_requested

    assert wide_scope_requested(text) is expected


async def test_ambiguity_cannot_be_resolved_by_another_model_mutation_in_the_same_turn(
    hass, timers,
):
    for name in ("Tea", "Pasta"):
        await invoke(hass, timers, {"action": "start", "minutes": 10, "name": name})
    tool = SatelliteTimerTool(hass, timers.auth)
    result = await invoke(hass, timers, {"action": "cancel"}, tool=tool)
    assert result.data["status"] == "clarification_required"
    result = await invoke(hass, timers, {"action": "cancel", "name": "Tea"}, tool=tool)
    assert result.error
    assert len(timers.manager.timers) == 2
    assert len((await invoke(hass, timers, {"action": "list"}, tool=tool)).data["timers"]) == 2


async def test_reading_status_does_not_need_remaining_mutation_budget(hass, timers):
    await invoke(hass, timers, {"action": "start", "seconds": 10})
    tool = SatelliteTimerTool(hass, timers.auth)
    tool.remaining_actions = 0
    result = await invoke(hass, timers, {"action": "status"}, tool=tool)
    assert not result.error
    assert result.data["timers"][0]["seconds_left"] == 10
    assert (await invoke(hass, timers, {"action": "cancel"}, tool=tool)).error
