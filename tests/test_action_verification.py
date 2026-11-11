"""Synthetic action readback: no real devices, services or credentials."""

import asyncio
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from custom_components.codex_assist.action_control import ActionOutcome, async_action_reply
from custom_components.codex_assist.action_verification import async_verify_action
from custom_components.codex_assist.codex_client import CodexTextDelta
from tests.ha_fakes import install_homeassistant_fakes


@pytest.fixture
def environment(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    from homeassistant.helpers import llm

    class NativeTool:
        name = "assist__HassTurnOff"
        intent_type = "HassTurnOff"

    monkeypatch.setattr(llm, "IntentTool", NativeTool, raising=False)
    permissions = ModuleType("homeassistant.auth.permissions.const")
    permissions.POLICY_READ = "read"
    exposure = ModuleType("homeassistant.components.homeassistant.exposed_entities")
    exposure.async_should_expose = lambda hass, assistant, eid: eid in hass.exposed
    monkeypatch.setitem(sys.modules, permissions.__name__, permissions)
    monkeypatch.setitem(sys.modules, exposure.__name__, exposure)
    states = {}
    hass = SimpleNamespace(states=SimpleNamespace(get=states.get), exposed=set())

    def add(entity_id="light.test", state="on", **attributes):
        result = SimpleNamespace(entity_id=entity_id, name="Test device", state=state,
                                 attributes=attributes)
        states[entity_id] = result
        hass.exposed.add(entity_id)
        return result

    return SimpleNamespace(hass=hass, tool=NativeTool(), add=add)


def contents(tool, *, success=("light.test",), failed=(), args=None, wrapped=True):
    call = SimpleNamespace(id="one", tool_name=tool.name, tool_args=args or {}, external=False)
    data = {"response_type": "action_done", "data": {
        "success": [{"id": eid, "type": "entity"} for eid in success],
        "failed": [{"id": eid, "type": "entity"} for eid in failed],
    }}
    result = SimpleNamespace(role="tool_result", tool_call_id="one")
    if wrapped:
        result.result = SimpleNamespace(data=data, error=False)
    else:
        result.tool_result = data
    return [SimpleNamespace(role="assistant", tool_calls=[call]), result]


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapped", [True, False])
async def test_exact_native_targets_receive_named_reported_state(environment, wrapped):
    env = environment
    env.add(state="off")
    outcome = await async_verify_action(
        env.hass, ActionOutcome("accepted"), contents(env.tool, wrapped=wrapped), [env.tool], None,
        timeout=0,
    )
    report, = outcome.targets
    assert report.entity_id == "light.test" and report.name == "Test device"
    assert report.verification == "reported_requested_state"
    assert report.expected_state == report.reported_state == "off"
    assert outcome.speech == "Test device: reports off."


@pytest.mark.asyncio
async def test_delayed_feedback_is_waited_for_without_another_command(environment):
    env = environment
    state = env.add()

    async def update():
        await asyncio.sleep(0.01)
        state.state = "off"

    task = asyncio.create_task(update())
    try:
        outcome = await async_verify_action(
            env.hass, ActionOutcome("accepted"), contents(env.tool), [env.tool], None,
            timeout=0.1, poll_interval=0.01,
        )
    finally:
        await task
    assert outcome.targets[0].verification == "reported_requested_state"
    assert not hasattr(env.hass, "services")  # No service bridge/refresh/retry exists.


@pytest.mark.asyncio
@pytest.mark.parametrize("state,attributes,expected", [
    ("on", {}, "not_observed"), ("off", {"assumed_state": True}, "optimistic_state"),
    ("unavailable", {}, "unavailable"), ("unknown", {}, "unavailable"),
])
async def test_no_false_confirmation_for_timeout_optimism_or_unavailability(
    environment, state, attributes, expected,
):
    env = environment
    env.add(state=state, **attributes)
    start = asyncio.get_running_loop().time()
    outcome = await async_verify_action(
        env.hass, ActionOutcome("accepted"), contents(env.tool), [env.tool], None,
        timeout=0.02, poll_interval=0.01,
    )
    assert asyncio.get_running_loop().time() - start < 0.2
    assert outcome.targets[0].verification == expected
    assert "not confirmed" in outcome.speech


@pytest.mark.asyncio
async def test_partial_result_preserves_each_failed_target_and_does_not_retry(environment):
    env = environment
    env.add(state="off")
    env.add("light.failed", state="on").name = "Other device"
    outcome = await async_verify_action(
        env.hass, ActionOutcome("partial"), contents(env.tool, failed=("light.failed",)),
        [env.tool], None, timeout=0,
    )
    assert [t.command_result for t in outcome.targets] == ["accepted", "failed"]
    assert outcome.targets[1].verification == "command_failed"
    assert "Other device: the command failed" in outcome.speech
    assert "Only part" in outcome.speech


@pytest.mark.asyncio
@pytest.mark.parametrize("domain,intent,state,args,attributes,status", [
    ("script", "HassTurnOn", "off", {}, {}, "no_verifiable_postcondition"),
    ("scene", "HassTurnOn", "2026-01-01", {}, {}, "no_verifiable_postcondition"),
    ("light", "HassToggle", "on", {}, {}, "no_verifiable_postcondition"),
    ("cover", "HassOpenCover", "open", {}, {"current_position": 50}, "not_observed"),
    ("cover", "HassOpenCover", "open", {}, {"current_position": 100},
     "reported_requested_state"),
    ("lock", "HassLock", "locked", {}, {}, "reported_requested_state"),
    ("climate", "HassClimateSetTemperature", "heat", {"temperature": 21},
     {"temperature": 21, "current_temperature": 16, "temperature_unit": "°C"},
     "reported_requested_setting"),
    ("climate", "HassClimateSetTemperature", "heat", {"temperature": 70,
     "temperature_unit": "°F"}, {"temperature": 21, "temperature_unit": "°C"},
     "no_verifiable_postcondition"),
])
async def test_domain_postconditions_do_not_confuse_acceptance_with_completion(
    environment, domain, intent, state, args, attributes, status,
):
    env = environment
    env.tool.intent_type = intent
    eid = f"{domain}.test"
    env.add(eid, state=state, **attributes)
    outcome = await async_verify_action(
        env.hass, ActionOutcome("accepted"), contents(env.tool, success=(eid,), args=args),
        [env.tool], None, timeout=0,
    )
    assert outcome.targets[0].verification == status
    if domain == "climate" and status == "reported_requested_setting":
        assert "target temperature" in outcome.speech and "room" not in outcome.speech


@pytest.mark.asyncio
async def test_hidden_or_permission_denied_entities_are_not_read(environment):
    env = environment
    env.add().name = "Private name"
    env.hass.exposed.clear()
    env.hass.states.get = lambda eid: pytest.fail("Must not read a hidden entity")
    original = ActionOutcome("accepted")
    outcome = await async_verify_action(
        env.hass, original, contents(env.tool), [env.tool], None, timeout=0,
    )
    assert not outcome.targets and "Private name" not in outcome.speech


@pytest.mark.asyncio
async def test_permission_revocation_during_wait_discards_private_details(environment):
    env = environment
    env.add()
    permitted = [True]
    user = SimpleNamespace(is_active=True, permissions=SimpleNamespace(
        check_entity=lambda *args: permitted[0],
    ))

    async def get_user(user_id):
        return user

    env.hass.auth = SimpleNamespace(async_get_user=get_user)

    async def revoke():
        await asyncio.sleep(0.005)
        permitted[0] = False

    task = asyncio.create_task(revoke())
    try:
        outcome = await async_verify_action(
            env.hass, ActionOutcome("accepted"), contents(env.tool), [env.tool],
            SimpleNamespace(user_id="caller"), timeout=0.1, poll_interval=0.01,
        )
    finally:
        await task
    assert not outcome.targets


@pytest.mark.asyncio
async def test_custom_tool_cannot_smuggle_native_targets_or_names(environment):
    env = environment
    env.add()
    impostor = SimpleNamespace(name=env.tool.name, intent_type="HassTurnOff")
    outcome = await async_verify_action(
        env.hass, ActionOutcome("accepted"), contents(impostor), [impostor], None, timeout=0,
    )
    assert not outcome.targets


@pytest.mark.asyncio
async def test_missing_duplicate_results_and_repeated_target_do_not_invent_success(environment):
    env = environment
    env.add(state="off")
    data = contents(env.tool)
    for invalid in (data[:1], data + [data[1]]):
        result = await async_verify_action(
            env.hass, ActionOutcome("accepted"), invalid, [env.tool], None, timeout=0,
        )
        assert not result.targets
    result = await async_verify_action(
        env.hass, ActionOutcome("accepted"),
        contents(env.tool, success=("light.test", "light.test")), [env.tool], None, timeout=0,
    )
    assert all(t.verification == "no_verifiable_postcondition" for t in result.targets)


@pytest.mark.asyncio
async def test_many_targets_share_one_wait_budget_and_bounded_reply_evidence(environment):
    env = environment
    ids = tuple(f"light.test_{index}" for index in range(20))
    for eid in ids:
        env.add(eid)
    start = asyncio.get_running_loop().time()
    result = await async_verify_action(
        env.hass, ActionOutcome("accepted"), contents(env.tool, success=ids), [env.tool], None,
        timeout=0.02, poll_interval=0.01,
    )
    assert asyncio.get_running_loop().time() - start < 0.2
    assert len(result.targets) == 16 and result.target_details_withheld
    assert all(t.verification == "not_observed" for t in result.targets)


@pytest.mark.asyncio
async def test_slow_account_check_is_bounded_and_cancellation_propagates(environment):
    env = environment
    env.add()

    async def slow_user(user_id):
        await asyncio.sleep(10)

    env.hass.auth = SimpleNamespace(async_get_user=slow_user)
    original = ActionOutcome("accepted")
    result = await asyncio.wait_for(async_verify_action(
        env.hass, original, contents(env.tool), [env.tool], SimpleNamespace(user_id="caller"),
        timeout=0.01,
    ), timeout=0.2)
    assert result is original

    async def cancelled(user_id):
        raise asyncio.CancelledError()

    env.hass.auth.async_get_user = cancelled
    with pytest.raises(asyncio.CancelledError):
        await async_verify_action(
            env.hass, original, contents(env.tool), [env.tool], SimpleNamespace(user_id="caller"),
        )


@pytest.mark.asyncio
async def test_personality_receives_only_authorized_target_facts_and_factual_fallback(environment):
    env = environment
    env.add(state="off")
    outcome = await async_verify_action(
        env.hass, ActionOutcome("accepted"), contents(env.tool), [env.tool], None, timeout=0,
    )
    captured = []

    class Client:
        async def stream_turn(self, **kwargs):
            captured.append(kwargs)
            yield CodexTextDelta(json.dumps({
                "outcome": "accepted", "reply": "Test device reports off. Most economical, sir.",
            }))

    reply = await async_action_reply(
        outcome, codex=Client(), model="test", instructions="Be dryly witty.",
        reasoning_effort="low", reasoning_summary="auto", text_verbosity="low",
    )
    assert reply == "Test device reports off. Most economical, sir."
    payload = json.loads(captured[0]["input_items"][0]["content"])
    assert payload["targets"][0]["name"] == "Test device"
    assert payload["targets"][0]["verification"] == "reported_requested_state"
    assert "entity_id" not in payload["targets"][0]
    assert captured[0]["tools"] == []
    assert "Be dryly witty." in captured[0]["instructions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["generic", "invalid", "failure"])
async def test_generic_or_broken_personality_reply_keeps_device_specific_facts(
    environment, response,
):
    env = environment
    env.add(state="off")
    outcome = await async_verify_action(
        env.hass, ActionOutcome("accepted"), contents(env.tool), [env.tool], None, timeout=0,
    )

    class Client:
        async def stream_turn(self, **kwargs):
            if response == "failure":
                raise RuntimeError("synthetic")
            yield CodexTextDelta("bad JSON" if response == "invalid" else json.dumps({
                "outcome": "accepted", "reply": "Home Assistant has accepted the request, sir.",
            }))

    assert await async_action_reply(
        outcome, codex=Client(), model="test", instructions="Be witty.",
        reasoning_effort="low", reasoning_summary="auto", text_verbosity="low",
    ) == "Test device: reports off."
