"""Native Assist routing and domain-independent action acknowledgements.

Recognition does not execute anything. Execution always remains on the existing
Assist LLM API, with its original caller, exposed entities and tool validators.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx


class ActionControlError(RuntimeError):
    """A request has no complete, trustworthy native tool result."""


@dataclass(frozen=True)
class ActionContext:
    """Small, allow-listed description of a natively recognised action."""

    operation: str
    target_domain: str | None = None


@dataclass(frozen=True)
class ActionOutcome:
    kind: str = "none"
    action_context: ActionContext | None = None

    @property
    def speech(self) -> str | None:
        # Native action_done acknowledges handling, not independent hardware
        # completion. Never invent a final state or script/scene completion.
        return {
            "accepted": "Home Assistant accepted that request.",
            "failed": "Sorry, Home Assistant couldn't complete that request.",
            "partial": "Home Assistant accepted only part of that request. I haven't retried it.",
            "unconfirmed": "Sorry, I couldn't confirm that request completed.",
        }.get(self.kind)


async def async_action_reply(
    outcome: ActionOutcome, *, codex: Any, model: str, instructions: str,
    reasoning_effort: str, reasoning_summary: str, text_verbosity: str,
) -> str:
    """Add personality without allowing a second action or losing the result.

    Only a fixed outcome and optional allow-listed action summary are input, not
    tool payloads, exceptions, raw arguments or user commands.
    The model writes the entire reply; outcome facts constrain its instructions.
    Model prose is guidance, not independently verified device-state evidence.
    """
    from .codex_client import CodexResponseItemDelta, CodexTextDelta

    fact = outcome.speech
    if fact is None:
        raise ValueError("An action outcome is required")
    try:
        async with asyncio.timeout(15):
            chunks = []
            size = 0
            stream = codex.stream_turn(
                model=model,
                instructions=(
                    f"{instructions}\n\n"
                    "Write a short action acknowledgement in the selected assistant's personality "
                    "and the user's language. Write the entire reply in that voice: no stock "
                    "sentence or fixed prefix/suffix is required. The provided outcome and its "
                    "explanation are facts to express naturally, not text to copy. "
                    "The optional action summary describes only the recognised "
                    "operation and target domain; it is not device-state evidence. "
                    "Accepted means HA accepted handling, "
                    "not verified physical completion. Never claim a final device state, change "
                    "failed/partial/unconfirmed into success, offer to retry, or issue commands. "
                    "Do not include diagnostics, secrets, questions, or tool calls. Return only "
                    "JSON with outcome and reply."
                ),
                input_items=[{"role": "user", "content": json.dumps({
                    "outcome": outcome.kind,
                    "fact": fact,
                    **({"action": {
                        "operation": outcome.action_context.operation,
                        "target_domain": outcome.action_context.target_domain,
                    }} if outcome.action_context else {}),
                })}],
                tools=[], reasoning_effort=reasoning_effort,
                reasoning_summary=reasoning_summary, text_verbosity=text_verbosity,
                text_format={"type": "json_schema", "name": "action_acknowledgement",
                             "strict": True, "schema": {
                                 "type": "object", "additionalProperties": False,
                                 "properties": {
                                     "outcome": {"type": "string", "enum": [outcome.kind]},
                                     "reply": {"type": "string"},
                                 }, "required": ["outcome", "reply"],
                             }},
            )
            try:
                async for delta in stream:
                    if isinstance(delta, CodexResponseItemDelta):
                        continue
                    if not isinstance(delta, CodexTextDelta):
                        return fact
                    size += len(delta.text)
                    if size > 2048:
                        return fact
                    chunks.append(delta.text)
            finally:
                await stream.aclose()
            result = json.loads("".join(chunks))
            if not isinstance(result, dict) or set(result) != {"outcome", "reply"}:
                return fact
            reply = result["reply"]
            if (result["outcome"] != outcome.kind or not isinstance(reply, str)
                    or not reply.strip() or len(reply) > 480
                    or any(ord(char) < 32 for char in reply)
                    or any(ActionOutcome(kind).speech in reply
                           for kind in ("accepted", "failed", "partial", "unconfirmed")
                           if kind != outcome.kind)):
                return fact
            return reply.strip()
    except (RuntimeError, ValueError, TypeError, TimeoutError, OSError, httpx.HTTPError):
        return fact


def intent_tool(tools: list[Any], intent_type: str, native_type: type | tuple) -> Any:
    """Find an actual native intent tool, including namespaced/legacy versions."""
    for tool in tools:
        underlying = tool
        for _ in range(3):
            if not hasattr(underlying, "tool"):
                break
            underlying = underlying.tool
        if not isinstance(underlying, native_type):
            continue
        if getattr(underlying, "intent_type", underlying.name) == intent_type:
            return tool
    return None


def read_only_tools(tools: list[Any], legacy_types: type | tuple = ()) -> set[str]:
    """Use tool capabilities, with a class-checked legacy native query adapter."""
    names = set()
    for tool in tools:
        underlying = tool
        for _ in range(3):
            if not hasattr(underlying, "tool"):
                break
            underlying = underlying.tool
        if (getattr(getattr(tool, "annotations", None), "read_only", False)
                or isinstance(underlying, legacy_types)):
            names.add(tool.name)
    return names


@dataclass(frozen=True)
class NativeRequestResult:
    """Indicate native handling and optionally carry sanitized action context."""

    action_context: ActionContext | None = None
    denied: bool = False


async def async_native_request(
    hass: Any, user_input: Any, chat_log: Any,
    *, allow_execution: bool = True,
) -> NativeRequestResult | None:
    """Route native-recognised requests through already-authorised Assist tools.

    No per-language verb regex, device list, direct service call or recursive
    conversation call. Unknown sentences and unavailable intent tools remain on
    the normal model path. Native target ambiguity is left to HA validation.
    """
    from homeassistant.components import conversation
    from homeassistant.helpers import llm

    from .schema_compat import to_openapi

    get_agent = getattr(conversation, "async_get_agent", None)
    if get_agent is None or not getattr(user_input, "text", ""):
        return None
    agent = get_agent(hass, conversation.HOME_ASSISTANT_AGENT)
    if agent is None or not hasattr(agent, "async_recognize_intent"):
        return None
    recognised = await agent.async_recognize_intent(user_input, strict_intents_only=True)
    if recognised is None:
        return None
    tool = intent_tool(
        getattr(chat_log.llm_api, "tools", []), recognised.intent.name,
        getattr(llm, "IntentTool", ()),
    )
    if tool is None:
        return None
    if recognised.unmatched_entities:
        raise ActionControlError("Native request has unmatched targets")
    if not allow_execution:
        return NativeRequestResult(denied=True)
    schema = to_openapi(tool.parameters, custom_serializer=chat_log.llm_api.custom_serializer)
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ActionControlError("Native tool has no parameter contract")
    arguments = {
        entity.name: entity.value for entity in recognised.entities_list
        if entity.name in properties
    }
    # The native recogniser often supplies scalar domain/device-class slots;
    # API tools may advertise lists. Adapt only the explicit schema shape.
    for name, value in list(arguments.items()):
        if properties[name].get("type") == "array" and not isinstance(value, list):
            arguments[name] = [value]
    tool_input = llm.ToolInput(
        id=f"native-{uuid4().hex}", tool_name=tool.name, tool_args=arguments,
    )
    async for _result in chat_log.async_add_assistant_content(conversation.AssistantContent(
        agent_id=user_input.agent_id, content=None, tool_calls=[tool_input],
    )):
        pass
    # Pass only fixed operation labels and a recognized, allow-listed entity
    # domain. Never forward names, IDs, or any of the native tool arguments.
    operations = {
        "HassTurnOn": "turn_on",
        "HassTurnOff": "turn_off",
        "HassToggle": "toggle",
    }
    operation = operations.get(recognised.intent.name)
    allowed_domains = {
        "alarm_control_panel", "automation", "climate", "cover", "fan",
        "humidifier", "input_boolean", "light", "lock", "media_player",
        "scene", "script", "switch", "vacuum", "water_heater",
    }
    domains = {
        entity.value.lower()
        for entity in recognised.entities_list
        if entity.name == "domain" and isinstance(entity.value, str)
        and entity.value.lower() in allowed_domains
    }
    context = ActionContext(operation, next(iter(domains)) if len(domains) == 1 else None)
    return NativeRequestResult(action_context=context if operation else None)


def action_outcome(contents: list[Any], read_only: set[str] | None = None) -> ActionOutcome:
    """Check only this round's call/result pairs; never infer a target state.

    Real native action acknowledgements, query responses and arbitrary tool data
    are distinct. Missing/duplicate, failed and partial results stop processing.
    This works with both legacy dictionaries and HA's wrapped ToolResult.
    """
    calls = [
        call for content in contents if getattr(content, "role", None) == "assistant"
        for call in (getattr(content, "tool_calls", None) or ())
        if not getattr(call, "external", False)
    ]
    if not calls:
        return ActionOutcome()
    ids = [call.id for call in calls]
    if len(set(ids)) != len(ids):
        return ActionOutcome("unconfirmed")
    accepted = 0
    failed = 0
    for call in calls:
        results = [
            content for content in contents
            if getattr(content, "role", None) == "tool_result"
            and getattr(content, "tool_call_id", None) == call.id
        ]
        if len(results) != 1:
            return ActionOutcome("unconfirmed")
        wrapped = getattr(results[0], "result", None)
        data = wrapped.data if wrapped is not None else getattr(results[0], "tool_result", None)
        if (getattr(wrapped, "error", False) or not isinstance(data, dict)
                or data.get("error") or data.get("response_type") == "error"
                or data.get("success") is False):
            failed += 1
            continue
        if data.get("failed"):
            accepted += bool(data.get("success"))
            failed += 1
            continue
        if data.get("response_type") == "query_answer" or call.tool_name in (read_only or ()):
            continue
        if data.get("response_type") != "action_done":
            # New native ToolResult explicitly carries the execution outcome.
            # Its success acknowledges the call, not a physical postcondition.
            if wrapped is not None or data.get("success") is True:
                accepted += 1
                continue
            return ActionOutcome("unconfirmed")
        targets = data.get("data")
        if not isinstance(targets, dict):
            return ActionOutcome("unconfirmed")
        success = targets.get("success")
        failures = targets.get("failed")
        if not isinstance(success, list) or not isinstance(failures, list):
            return ActionOutcome("unconfirmed")
        if any(not isinstance(target, dict) or not target.get("id") for target in success):
            return ActionOutcome("unconfirmed")
        accepted += bool(success)
        failed += bool(failures)
        if not success and not failures:
            return ActionOutcome("unconfirmed")
    if failed:
        return ActionOutcome("partial" if accepted else "failed")
    return ActionOutcome("accepted" if accepted else "none")
