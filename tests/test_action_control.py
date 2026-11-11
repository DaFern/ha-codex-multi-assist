"""Shared action evidence tests; no household-specific names or identifiers."""

from __future__ import annotations

import asyncio
import importlib
import json
from types import SimpleNamespace

import pytest

from custom_components.codex_assist.action_control import (
    ActionContext,
    ActionOutcome,
    action_outcome,
    async_action_reply,
    async_native_request,
    intent_tool,
    read_only_tools,
)
from custom_components.codex_assist.codex_client import (
    CodexResponseItemDelta,
    CodexTextDelta,
    CodexToolCall,
    CodexToolCallDelta,
)
from tests.ha_fakes import install_homeassistant_fakes


def evidence(data, *, wrapped=True, error=False, call_id="current", tool="TestTool"):
    call = SimpleNamespace(id=call_id, tool_name=tool, external=False)
    result = SimpleNamespace(role="tool_result", tool_call_id=call_id)
    if wrapped:
        result.result = SimpleNamespace(data=data, error=error)
    else:
        result.tool_result = data
    return [SimpleNamespace(role="assistant", tool_calls=[call]), result]


@pytest.mark.parametrize("domain", [
    "light", "switch", "fan", "lock", "cover", "climate", "media_player", "scene", "script",
    "vacuum", "humidifier", "water_heater", "input_boolean", "automation",
])
@pytest.mark.parametrize("wrapped", [True, False])
def test_native_acknowledgement_is_domain_independent_and_never_claims_final_state(domain, wrapped):
    data = {"response_type": "action_done", "data": {
        "success": [{"id": f"{domain}.test", "type": "entity", "name": "Test device"}],
        "failed": [],
    }}
    outcome = action_outcome(evidence(data, wrapped=wrapped))
    assert outcome.kind == "accepted"
    assert outcome.speech == "Home Assistant accepted that request."
    assert "off" not in outcome.speech
    assert "completed" not in outcome.speech


@pytest.mark.parametrize("data,wrapped_error,kind", [
    ({"error": "IntentHandleError"}, False, "failed"),
    ({}, True, "failed"),
    ({"response_type": "error", "data": {}}, False, "failed"),
    ({"response_type": "action_done", "data": {"success": [], "failed": []}}, False, "unconfirmed"),
    ({"response_type": "action_done", "data": {
        "success": [{"id": "cover.test"}], "failed": [{"id": "cover.other"}]}}, False, "partial"),
    ({"response_type": "action_done", "data": {"success": [], "failed": [{"id": "lock.test"}]}},
     False, "failed"),
    ({"response_type": "action_done", "data": {}}, False, "unconfirmed"),
    ({"success": False}, False, "failed"),
    ({"success": True, "failed": ["test-target"]}, False, "partial"),
    ({"response_type": "action_done", "data": {"success": [{}], "failed": []}},
     False, "unconfirmed"),
    ({"response_type": "query_answer", "data": {"value": 21}}, False, "none"),
])
def test_failed_partial_missing_and_query_results_are_not_fabricated_success(
    data, wrapped_error, kind,
):
    assert action_outcome(evidence(data, error=wrapped_error)).kind == kind


def test_new_tool_protocol_ack_and_legacy_unknown_are_distinct():
    assert action_outcome(evidence({}, wrapped=True)).kind == "accepted"
    assert action_outcome(evidence({}, wrapped=False)).kind == "unconfirmed"
    assert action_outcome(evidence({"success": True}, wrapped=False)).kind == "accepted"


def test_read_only_capability_and_legacy_native_class_are_not_actions():
    class LegacyQuery:
        name = "LegacyQuery"

    readonly = SimpleNamespace(name="ReadOnly", annotations=SimpleNamespace(read_only=True))
    mutable = SimpleNamespace(name="Mutate", annotations=SimpleNamespace(read_only=False))
    names = read_only_tools([readonly, mutable, LegacyQuery()], LegacyQuery)
    assert names == {"ReadOnly", "LegacyQuery"}
    for name in names:
        assert action_outcome(evidence({"state": "on"}, tool=name), names).kind == "none"
    result = action_outcome(evidence({"error": "ReadFailed"}, tool="ReadOnly"), names)
    assert result.kind == "failed"


def test_only_current_paired_results_can_acknowledge_an_action():
    contents = evidence({})
    assert action_outcome(contents[:1]).kind == "unconfirmed"
    contents[1].tool_call_id = "old-call"
    assert action_outcome(contents).kind == "unconfirmed"
    assert action_outcome([]).speech is None
    contents = evidence({})
    assert action_outcome(contents + contents).kind == "unconfirmed"


def test_mixed_success_and_failure_is_partial_not_complete():
    contents = evidence({"success": True}, call_id="one") + evidence(
        {"error": "Failed"}, call_id="two",
    )
    assert action_outcome(contents).kind == "partial"


def test_intent_selection_requires_native_class_including_namespaced_legacy():
    class NativeTool:
        name = "HassTestAction"

    tool = NativeTool()
    wrapped = SimpleNamespace(name="assist__HassTestAction", tool=tool)
    assert intent_tool([wrapped], "HassTestAction", NativeTool) is wrapped
    assert intent_tool([SimpleNamespace(name=tool.name)], tool.name, NativeTool) is None
    assert intent_tool([tool], "AnotherIntent", NativeTool) is None


@pytest.fixture
def conversation_module(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    module = importlib.import_module("custom_components.codex_assist.conversation")
    return importlib.reload(module)


@pytest.mark.asyncio
async def test_native_recognition_uses_existing_tool_contract_and_original_input(
    conversation_module, monkeypatch,
):
    from homeassistant.components import conversation
    from homeassistant.helpers import llm

    class NativeTool:
        name = "HassTurnOff"
        parameters = {"type": "object", "properties": {
            "name": {"type": "string"}, "domain": {"type": "array", "items": {"type": "string"}},
        }}

    monkeypatch.setattr(llm, "IntentTool", NativeTool, raising=False)
    monkeypatch.setattr(
        conversation, "HOME_ASSISTANT_AGENT", "conversation.home_assistant", raising=False,
    )
    user_input = SimpleNamespace(text="Turn off the test fan", agent_id="conversation.test")
    recognised = SimpleNamespace(
        intent=SimpleNamespace(name="HassTurnOff"), unmatched_entities=False,
        entities_list=[SimpleNamespace(name=name, value=value) for name, value in (
            ("name", "Test fan"), ("domain", "fan"), ("unaccepted_slot", "never forwarded"),
        )],
    )
    received = []

    class NativeAgent:
        async def async_recognize_intent(self, actual_input, *, strict_intents_only):
            assert actual_input is user_input
            assert strict_intents_only is True
            return recognised

    monkeypatch.setattr(conversation, "async_get_agent", lambda *args: NativeAgent(), raising=False)

    class Chat:
        llm_api = SimpleNamespace(tools=[NativeTool()], custom_serializer=None)

        async def async_add_assistant_content(self, content):
            received.append(content)
            yield None

    denied_result = await async_native_request(
        object(), user_input, Chat(), allow_execution=False,
    )
    assert denied_result.denied is True
    assert received == []

    native_result = await async_native_request(object(), user_input, Chat())
    assert native_result is not None
    assert native_result.action_context.operation == "turn_off"
    assert native_result.action_context.target_domain == "fan"
    assert len(received) == 1
    call = received[0].tool_calls[0]
    assert call.tool_name == "HassTurnOff"
    assert call.tool_args == {"name": "Test fan", "domain": ["fan"]}


@pytest.mark.asyncio
async def test_round_discards_premature_speech_for_any_tool_and_keeps_private_replay(
    conversation_module,
):
    call = CodexToolCallDelta(CodexToolCall(
        id="call-one", name="HassClimateSetTemperature", arguments={"temperature": 21},
    ))
    private = CodexResponseItemDelta({"type": "reasoning", "encrypted_content": "synthetic"})

    async def stream():
        yield CodexTextDelta("The heating is set.")
        yield private
        yield call

    result = [item async for item in conversation_module._action_aware_stream(stream())]
    assert result == [private, call]


@pytest.mark.asyncio
async def test_general_answer_and_clarification_survive_without_device_classifier(
    conversation_module,
):
    async def stream():
        yield CodexTextDelta("Which device ")
        yield CodexTextDelta("do you mean?")

    assert [item.text async for item in conversation_module._action_aware_stream(stream())] == [
        "Which device ", "do you mean?",
    ]


@pytest.mark.asyncio
async def test_interrupted_response_dispatches_nothing_and_retries_nothing(conversation_module):
    async def stream():
        yield CodexToolCallDelta(CodexToolCall(id="one", name="TestTool", arguments={}))
        raise RuntimeError("synthetic transport failure")

    delivered = []
    with pytest.raises(RuntimeError, match="synthetic transport failure"):
        async for item in conversation_module._action_aware_stream(stream()):
            delivered.append(item)
    assert delivered == []


def test_fixed_partial_and_failure_replies_do_not_expose_raw_errors():
    for kind in ("accepted", "failed", "partial", "unconfirmed"):
        assert ActionOutcome(kind).speech


@pytest.mark.asyncio
@pytest.mark.parametrize("profile,reply", [
    ("Use dry British wit.", "Test lamp reports off. A triumph of restraint."),
    ("Be warm and encouraging.", "Test lamp reports off. One less thing to worry about."),
    ("Be theatrical and sarcastic.", "Test lamp reports off. Behold, civilisation advances."),
    ("Be plain and minimal. No jokes.", "Test lamp reports off."),
])
async def test_reply_guidance_preserves_each_profile_without_forcing_one_character(
    profile, reply, caplog,
):
    import logging

    caplog.set_level(logging.INFO, logger="custom_components.codex_assist.action_control")
    calls = []

    class Client:
        async def stream_turn(self, **kwargs):
            calls.append(kwargs)
            yield CodexTextDelta(json.dumps({"outcome": "accepted", "reply": reply}))

    result = await async_action_reply(
        ActionOutcome("accepted"), codex=Client(), model="test", instructions=profile,
        reasoning_effort="low", reasoning_summary="auto", text_verbosity="low",
    )
    assert result == reply  # Scripted output proves routing, not real-model style.
    prompt = calls[0]["instructions"]
    assert prompt.startswith(profile)
    assert "one brief characteristic flourish" in prompt
    assert "do not force jokes" in prompt
    assert "fallback reference, not a script to recite" in prompt
    assert "not verified physical completion" in prompt
    assert calls[0]["tools"] == []
    assert "Action reply: result=generated reason=valid outcome=accepted" in caplog.text
    assert profile not in caplog.text and reply not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["accepted", "failed", "partial", "unconfirmed"])
@pytest.mark.parametrize("personality", ["Speak like a pirate.", "Use quiet scientific wit."])
async def test_action_reply_uses_any_personality_but_preserves_authoritative_outcome(
    kind, personality,
):
    outcome = ActionOutcome(kind)
    calls = []
    styled = {
        "accepted": "Aye, your request is in hand.",
        "failed": "Alas, that request met a rather stubborn obstacle.",
        "partial": "Some of that went through; the rest did not. I have not repeated it.",
        "unconfirmed": "The outcome remains a mystery; I cannot confirm it went through.",
    }[kind]

    class Client:
        async def stream_turn(self, **kwargs):
            calls.append(kwargs)
            yield CodexTextDelta(json.dumps({
                "outcome": kind, "reply": styled,
            }))

    reply = await async_action_reply(
        outcome, codex=Client(), model="test-model", instructions=personality,
        reasoning_effort="low", reasoning_summary="auto", text_verbosity="low",
    )
    assert reply == styled
    assert outcome.speech not in reply
    assert len(calls) == 1
    assert calls[0]["tools"] == []
    assert calls[0]["instructions"].startswith(personality)
    assert "no stock sentence" in calls[0]["instructions"]
    assert json.loads(calls[0]["input_items"][0]["content"]) == {
        "outcome": kind, "fact": outcome.speech,
    }


@pytest.mark.asyncio
async def test_action_reply_gets_only_sanitized_action_context():
    calls = []

    class Client:
        async def stream_turn(self, **kwargs):
            calls.append(kwargs)
            yield CodexTextDelta(json.dumps({
                "outcome": "accepted", "reply": "The lights are having a quiet moment.",
            }))

    outcome = ActionOutcome("accepted", ActionContext("turn_off", "light"))
    assert await async_action_reply(
        outcome, codex=Client(), model="test", instructions="Use dry wit.",
        reasoning_effort="low", reasoning_summary="auto", text_verbosity="low",
    ) == "The lights are having a quiet moment."
    payload = json.loads(calls[0]["input_items"][0]["content"])
    assert payload == {
        "outcome": "accepted",
        "fact": outcome.speech,
        "action": {"operation": "turn_off", "target_domain": "light"},
    }
    assert "office" not in str(payload)
    assert "entity_id" not in str(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    "", "The heating is set.", "{}", "[]", "null",
    json.dumps({"outcome": "failed", "reply": ActionOutcome("accepted").speech}),
    json.dumps({"outcome": "accepted", "reply": "   "}),
    json.dumps({"outcome": "accepted", "reply": "x" * 500 + ActionOutcome("accepted").speech}),
    json.dumps({"outcome": "accepted", "reply": ActionOutcome("accepted").speech,
                "extra": "not accepted"}),
    json.dumps({"outcome": "accepted", "reply": 42}),
])
async def test_bad_styled_response_falls_back_without_publishing_partial_text(bad):
    class Client:
        async def stream_turn(self, **kwargs):
            yield CodexTextDelta(bad)

    assert await async_action_reply(
        ActionOutcome("accepted"), codex=Client(), model="test", instructions="Custom persona",
        reasoning_effort="low", reasoning_summary="auto", text_verbosity="low",
    ) == ActionOutcome("accepted").speech


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    RuntimeError, ValueError, TimeoutError, asyncio.CancelledError,
])
async def test_reply_failure_never_retries_and_cancellation_propagates(failure):
    calls = []

    class Client:
        async def stream_turn(self, **kwargs):
            calls.append(kwargs)
            yield CodexTextDelta("incomplete")
            raise failure()

    async def run():
        return await async_action_reply(
            ActionOutcome("partial"), codex=Client(), model="test", instructions="Persona",
            reasoning_effort="low", reasoning_summary="auto", text_verbosity="low",
        )

    if failure is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            await run()
    else:
        assert await run() == ActionOutcome("partial").speech
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_reply_tool_call_is_never_dispatched_and_stream_is_closed():
    closed = []

    class Client:
        async def stream_turn(self, **kwargs):
            try:
                yield CodexToolCallDelta(CodexToolCall(
                    id="forbidden", name="AnyTool", arguments={},
                ))
                raise AssertionError("Must not continue after an unexpected tool call")
            finally:
                closed.append(True)

    assert await async_action_reply(
        ActionOutcome("failed"), codex=Client(), model="test", instructions="Persona",
        reasoning_effort="low", reasoning_summary="auto", text_verbosity="low",
    ) == ActionOutcome("failed").speech
    assert closed == [True]
