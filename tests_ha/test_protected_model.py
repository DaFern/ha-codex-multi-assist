"""Bounded model completion/dispatch, without network, native discovery or history."""

import json
from types import SimpleNamespace

import pytest
from homeassistant.core import Context

from custom_components.codex_assist.satellite_runtime import satellite_tools_supported

if not satellite_tools_supported():
    pytest.skip("Modern native tools required", allow_module_level=True)

import probatio
from homeassistant.helpers import llm

from custom_components.codex_assist.codex_client import (
    CodexResponseItemDelta,
    CodexTextDelta,
    CodexToolCall,
    CodexToolCallDelta,
)
from custom_components.codex_assist.protected_model import async_fixed_tool_turn


@pytest.fixture
def fixed():
    calls = []
    context = Context(user_id="unchanged-kiosk")

    class Tool(llm.Tool):
        name = "codex_assist__test_fixed"
        description = "A synthetic fixed query tool"
        parameters = probatio.Schema({probatio.Required("query"): str})

        async def async_call(self, _hass, tool_input, llm_context):
            assert llm_context.context is context
            calls.append(tool_input.tool_args)
            return llm.ToolResult(data={"response_type": "query_answer", "value": "safe data"})

    return SimpleNamespace(
        context=context, calls=calls,
        payload={"prompt": "Only filtered safe data", "tools": [Tool()]},
        profile=SimpleNamespace(model="synthetic", reasoning_effort="low",
                                reasoning_summary="auto", text_verbosity="low"),
    )


def request(call_id="call-1", name="codex_assist__test_fixed", arguments=None):
    return CodexToolCallDelta(CodexToolCall(
        call_id, name, {"query": "test"} if arguments is None else arguments,
    ))


async def invoke(hass, fixed, responses, text="Test"):
    seen = []

    class Client:
        async def stream_turn(self, **kwargs):
            seen.append(kwargs)
            for item in responses[len(seen) - 1]:
                if isinstance(item, Exception):
                    raise item
                yield item

    result = await async_fixed_tool_turn(
        hass, Client(), fixed.profile, fixed.payload, fixed.context, text, "en",
    )
    return result, seen


async def test_query_round_retains_only_this_turn_and_supplied_tools(hass, fixed):
    output = {"type": "function_call", "call_id": "call-1", "name": "codex_assist__test_fixed",
              "arguments": '{"query":"test"}'}
    (result, speech), seen = await invoke(hass, fixed, [
        [CodexResponseItemDelta(output), request(), CodexTextDelta("Do not speak this")],
        [CodexTextDelta("Safe final answer.")],
    ])
    assert result == {"status": "completed", "completed": 0}
    assert speech == "Safe final answer."
    assert fixed.calls == [{"query": "test"}]
    assert seen[0]["input_items"] == [{"role": "user", "content": "Test"}]
    assert seen[1]["input_items"][-1]["type"] == "function_call_output"
    assert seen[1]["input_items"][-1]["call_id"] == "call-1"
    assert {tool["name"] for tool in seen[0]["tools"]} == {"codex_assist__test_fixed"}


@pytest.mark.parametrize("case", ["unknown", "duplicate", "partial", "invalid", "too_many"])
async def test_untrusted_or_incomplete_batch_never_executes(hass, fixed, case):
    sequence = {
        "unknown": [request(), request("call-2", "HassTurnOn")],
        "duplicate": [request(), request()],
        "partial": [request(), RuntimeError("No response.completed")],
        "invalid": [request(), request("call-2", arguments={"query": 2})],
        "too_many": [request(f"call-{i}") for i in range(9)],
    }[case]
    try:
        result, _seen = await invoke(hass, fixed, [sequence])
    except (RuntimeError, probatio.Invalid):
        pass
    else:
        assert result[0]["status"] in {"denied", "unconfirmed"}
    assert fixed.calls == []


async def test_provider_tool_error_cannot_be_spoken_as_success(hass, fixed):
    async def denied(*args):
        return llm.ToolResult(data={"error": "denied"}, error=True)

    fixed.payload["tools"][0].async_call = denied
    (result, speech), _seen = await invoke(hass, fixed, [[
        CodexTextDelta("Everything is definitely on."), request(),
    ]])
    assert result["status"] == "denied"
    assert speech == "That control is not permitted."


async def test_wrong_direction_is_replanned_before_effects_not_silently_substituted(hass, fixed):
    tool = fixed.payload["tools"][0]
    tool.name = "codex_assist__guest_on_off"
    tool.parameters = probatio.Schema({
        probatio.Required("operation"): probatio.In(("turn_on", "turn_off")),
        probatio.Required("entity_ids"): [str],
    })

    async def accepted(_hass, tool_input, _context):
        fixed.calls.append(tool_input.tool_args)
        return llm.ToolResult(data={"status": "accepted", "completed": 1})

    tool.async_call = accepted

    def proposal(call_id, operation):
        args = {"operation": operation, "entity_ids": ["light.test"]}
        return [
            CodexResponseItemDelta({
                "type": "function_call", "call_id": call_id, "name": tool.name,
                "arguments": json.dumps(args),
            }),
            request(call_id, tool.name, args),
        ]

    (result, _speech), seen = await invoke(hass, fixed, [
        proposal("wrong", "turn_on"), proposal("corrected", "turn_off"),
    ], text="No, off!")
    assert result["status"] == "completed"
    assert fixed.calls == [{"operation": "turn_off", "entity_ids": ["light.test"]}]
    assert "needs_correction" in seen[1]["input_items"][-1]["output"]
    assert "latest user's correction" in seen[0]["instructions"]


async def test_compound_request_executes_all_completed_tool_calls_not_just_first(hass, fixed):
    async def accepted(_hass, tool_input, _context):
        fixed.calls.append(tool_input.tool_args)
        return llm.ToolResult(data={"status": "accepted", "completed": 1})

    fixed.payload["tools"][0].async_call = accepted
    (result, speech), _seen = await invoke(hass, fixed, [[
        request("first", arguments={"query": "first"}),
        request("second", arguments={"query": "second"}),
    ]])
    assert fixed.calls == [{"query": "first"}, {"query": "second"}]
    assert result == {"status": "completed", "completed": 2}
    assert speech == "Okay."


async def test_partial_compound_failure_reports_successful_count_without_replaying(hass, fixed):
    async def accept_then_fail(_hass, tool_input, _context):
        fixed.calls.append(tool_input.tool_args)
        return (
            llm.ToolResult(data={"status": "accepted", "completed": 1})
            if len(fixed.calls) == 1 else llm.ToolResult(data={"error": "unavailable"}, error=True)
        )

    fixed.payload["tools"][0].async_call = accept_then_fail
    (result, _speech), _seen = await invoke(hass, fixed, [[
        request("first", arguments={"query": "first"}),
        request("second", arguments={"query": "second"}),
    ]])
    assert len(fixed.calls) == 2 and result == {"status": "partial", "completed": 1}


async def test_invalid_arguments_get_bounded_repair_instead_of_silent_exception(hass, fixed):
    (result, speech), seen = await invoke(hass, fixed, [
        [request("bad", arguments={"query": 1})],
        [CodexTextDelta("Which device did you mean?")],
    ])
    assert fixed.calls == [] and result["status"] == "completed"
    assert speech == "Which device did you mean?"
    assert "needs_correction" in seen[1]["input_items"][-1]["output"]
