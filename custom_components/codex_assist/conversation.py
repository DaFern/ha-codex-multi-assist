from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from copy import copy
from dataclasses import is_dataclass, replace
from pathlib import Path
from typing import Any

import httpx
from homeassistant.components import conversation
from homeassistant.components.conversation import AssistantContentDeltaDict
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent, llm
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.json import json_dumps

from . import DOMAIN
from .agent_profiles import PRIMARY_AGENT_ID, AgentProfile, get_agent_profiles
from .codex_auth import (
    CodexAuthClient,
    CodexAuthTemporaryError,
    CodexReauthRequiredError,
    CodexTokenSet,
)
from .codex_client import (
    CodexAuthenticationError,
    CodexClient,
    CodexRateLimitError,
    CodexResponseItemDelta,
    CodexStreamDelta,
    CodexTextDelta,
    CodexToolCallDelta,
    codex_session_id,
    codex_user_content_with_images,
)
from .codex_protocol import CodexNativeState, native_state_from_response_items
from .codex_runtime import runtime_token_coordinator
from .schema_compat import to_openapi
from .speaker_packet import WIRE_PREFIX
from .voice_match import (
    CONF_VOICE_MATCH_KEY,
    PacketError,
    personal_instructions,
    runtime_for_entry,
    scoped_contents,
)

MAX_TOOL_ITERATIONS = 5
MAX_IMAGE_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_IMAGE_ATTACHMENTS = 4
MAX_TOTAL_IMAGE_ATTACHMENT_BYTES = 20 * 1024 * 1024
LOGGER = logging.getLogger(__name__)
_INTEGRATION_DIRECTORY = Path(__file__).parent
_AUTH_FAILURE_TEXT = "Codex Assist needs attention in Home Assistant."
_ERROR_RESPONSE_INSTRUCTIONS = (
    "Keep error responses short. Do not volunteer technical diagnostics, raw error codes, "
    "request IDs, HTTP details, stack traces, or issue-reporting instructions. Provide "
    "troubleshooting details only when the user explicitly asks for them."
)
_CLARIFICATION_INSTRUCTIONS = (
    "When clarification is required, ask one concise, direct question as the final "
    "sentence, ending with the appropriate question mark for the user's language and "
    "nothing after it. Resolve ambiguous actions or targets before executing them. "
    "Do not add unnecessary closing questions after ordinary answers, completed "
    "actions, or cancellation."
)
_WEB_SEARCH_SPEECH_INSTRUCTIONS = (
    "When using web search, do not include raw URLs, markdown links, or a Source/Sources "
    "section in the response text. Refer to sources by human-readable names only."
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [CodexAssistConversationEntity(entry, profile) for profile in get_agent_profiles(entry)]
    )


class CodexAssistConversationEntity(
    conversation.ConversationEntity,
    conversation.AbstractConversationAgent,
):
    _attr_has_entity_name = True
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL
    _attr_supports_streaming = True

    def __init__(self, entry: ConfigEntry, profile: AgentProfile | None = None) -> None:
        self.entry = entry
        self.profile = profile or get_agent_profiles(entry)[0]
        self._attr_name = self.profile.name
        self._attr_unique_id = (
            entry.entry_id
            if self.profile.agent_id == PRIMARY_AGENT_ID
            else f"{entry.entry_id}_{self.profile.agent_id}"
        )

    @property
    def supported_languages(self) -> list[str] | str:
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.profile.agent_id == PRIMARY_AGENT_ID:
            conversation.async_set_agent(self.hass, self.entry, self)

    async def async_will_remove_from_hass(self) -> None:
        if self.profile.agent_id == PRIMARY_AGENT_ID:
            conversation.async_unset_agent(self.hass, self.entry)
        await super().async_will_remove_from_hass()

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        model = self.profile.model or "gpt-5.4"
        prompt = self.profile.prompt
        reasoning_effort = self.profile.reasoning_effort
        reasoning_summary = self.profile.reasoning_summary
        text_verbosity = self.profile.text_verbosity
        web_search = self.profile.web_search

        response = intent.IntentResponse(language=user_input.language)
        boundary = None
        request_turn = None
        speaker_scope = None
        preferences = ""
        key = getattr(self.entry, "options", {}).get(CONF_VOICE_MATCH_KEY, "")
        packet_text = None
        input_text = getattr(user_input, "text", "")
        try:
            runtime = runtime_for_entry(self.entry)
            packet_text = runtime.handoffs.consume(key, input_text)
            prepared_request = runtime.prepare_request(
                key, input_text, chat_log.content,
                user_input.conversation_id, user_input.agent_id,
                packet_text=packet_text,
            )
            _clean = prepared_request.text
            preferences = prepared_request.instructions
            boundary = prepared_request.boundary
            speaker_scope = prepared_request.scope
            if prepared_request.verified:
                LOGGER.info(
                    "Voice Match receive: request=%s result=%s instructions_present=%s",
                    prepared_request.diagnostic_tag,
                    "recognised" if prepared_request.voice is not None else "neutral",
                    bool(preferences),
                )
            if _clean != getattr(user_input, "text", ""):
                if is_dataclass(user_input):
                    user_input = replace(user_input, text=_clean)
                else:
                    user_input = copy(user_input)
                    user_input.text = _clean
            if boundary is not None:
                request_turn = next(
                    item for item in reversed(chat_log.content)
                    if getattr(item, "role", None) == "user"
                )
        except PacketError:
            from .speaker_packet import diagnostic_tag

            LOGGER.info(
                "Voice Match receive: request=%s result=rejected instructions_present=False",
                diagnostic_tag(packet_text or input_text) or "unavailable",
            )
            runtime_for_entry(self.entry).invalidate(user_input.conversation_id)
            chat_log.async_add_assistant_content_without_tools(conversation.AssistantContent(
                agent_id=user_input.agent_id,
                content="Voice Match pairing needs attention. Please check its settings.",
            ))
            return conversation.async_get_result_from_chat_log(user_input, chat_log)

        from .speaker_automation import DATA_SPEAKER_AUTOMATIONS, DispatchResult

        try:
            automation_result = DispatchResult()
            if (prepared_request.verified
                    and (bridge := self.hass.data.get(DATA_SPEAKER_AUTOMATIONS)) is not None):
                automation_result = await bridge.dispatch(prepared_request, user_input)
        except Exception:
            # An action may already have run. Do not fall through to the model
            # or replay it, and never expose automation exception payloads.
            chat_log.async_add_assistant_content_without_tools(conversation.AssistantContent(
                agent_id=user_input.agent_id,
                content="Sorry, I couldn't complete that voice automation.",
            ))
            return conversation.async_get_result_from_chat_log(user_input, chat_log)
        if automation_result.matched:
            chat_log.async_add_assistant_content_without_tools(conversation.AssistantContent(
                agent_id=user_input.agent_id,
                content=(automation_result.response
                         or "There isn't a configured response for that voice request."),
            ))
            return conversation.async_get_result_from_chat_log(user_input, chat_log)
        try:
            await chat_log.async_provide_llm_data(
                user_input.as_llm_context(DOMAIN),
                llm.LLM_API_ASSIST,
                prompt,
                user_input.extra_system_prompt,
            )
        except conversation.ConverseError as err:
            return err.as_conversation_result()

        http_client = get_async_client(self.hass)
        auth_client = CodexAuthClient(http_client=http_client)
        try:
            tokens = await runtime_token_coordinator(self.entry).resolve(
                lambda: self.entry.data,
                auth_client=auth_client,
                async_update_entry_data=lambda data: self.hass.config_entries.async_update_entry(
                    self.entry,
                    data=data,
                ),
            )
        except CodexReauthRequiredError as err:
            _log_request_failure(
                err, stage="authentication", reauth="start", level=logging.WARNING,
            )
            return _start_reauth_result(self.hass, self.entry, response, user_input)
        except (CodexAuthTemporaryError, RuntimeError) as err:
            _log_request_failure(err, stage="authentication")
            chat_log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=user_input.agent_id,
                    content=_request_failure_text(err),
                )
            )
            return conversation.async_get_result_from_chat_log(user_input, chat_log)

        codex = CodexClient(
            http_client=http_client,
            access_token=tokens.access_token,
            session_id=_codex_session_id_for_profile(
                self.entry.entry_id, self.profile, speaker_scope
            ),
        )
        try:
            for _iteration in range(MAX_TOOL_ITERATIONS + 1):
                allow_tools = _iteration < MAX_TOOL_ITERATIONS
                try:
                    tool_call_requested = await _stream_codex_turn_into_chat_log(
                        chat_log=chat_log,
                        codex=codex,
                        entity_id=self.entity_id or "",
                        model=model,
                        instructions=personal_instructions(_instructions_for_turn(
                            chat_log, prompt, web_search=web_search
                        ), preferences, request_tag=prepared_request.diagnostic_tag),
                        input_items=await _codex_input_from_chat_log(
                            self.hass, chat_log, user_input.agent_id, boundary, request_turn
                        ),
                        tools=(
                            _codex_tools_from_chat_log(chat_log, enable_web_search=web_search)
                            if allow_tools
                            else []
                        ),
                        reasoning_effort=reasoning_effort,
                        reasoning_summary=reasoning_summary,
                        text_verbosity=text_verbosity,
                        allow_tools=allow_tools,
                    )
                except CodexAuthenticationError as err:
                    if not err.retry_allowed:
                        raise
                    _log_request_failure(
                        err, stage="model_request", retry="once", level=logging.WARNING,
                    )
                    try:
                        tokens = await _refresh_runtime_tokens(
                            self.hass,
                            self.entry,
                            auth_client,
                            tokens,
                        )
                    except CodexReauthRequiredError as refresh_err:
                        _log_request_failure(
                            refresh_err, stage="token_refresh", reauth="start",
                            level=logging.WARNING,
                        )
                        return _start_reauth_result(
                            self.hass,
                            self.entry,
                            response,
                            user_input,
                        )
                    codex = codex.with_access_token(tokens.access_token)
                    try:
                        tool_call_requested = await _stream_codex_turn_into_chat_log(
                            chat_log=chat_log,
                            codex=codex,
                            entity_id=self.entity_id or "",
                            model=model,
                            instructions=personal_instructions(_instructions_for_turn(
                                chat_log, prompt, web_search=web_search
                            ), preferences, request_tag=prepared_request.diagnostic_tag),
                            input_items=await _codex_input_from_chat_log(
                                self.hass, chat_log, user_input.agent_id, boundary, request_turn
                            ),
                            tools=(
                                _codex_tools_from_chat_log(chat_log, enable_web_search=web_search)
                                if allow_tools
                                else []
                            ),
                            reasoning_effort=reasoning_effort,
                            reasoning_summary=reasoning_summary,
                            text_verbosity=text_verbosity,
                            allow_tools=allow_tools,
                        )
                    except CodexAuthenticationError as retry_err:
                        _log_request_failure(
                            retry_err, stage="model_retry", reauth="start", level=logging.WARNING,
                        )
                        return _start_reauth_result(
                            self.hass,
                            self.entry,
                            response,
                            user_input,
                        )
                if not tool_call_requested:
                    break
        except CodexRateLimitError as err:
            _log_request_failure(err, stage="model_request", level=logging.WARNING)
            chat_log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=user_input.agent_id,
                    content=_request_failure_text(err),
                )
            )
        except (httpx.HTTPError, RuntimeError) as err:
            _log_request_failure(err, stage="model_request")
            text = _request_failure_text(err)
            chat_log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=user_input.agent_id,
                    content=text,
                )
            )
        except (ValueError, TypeError) as err:
            _log_request_failure(err, stage="request_preparation_or_tool_processing")
            text = _request_failure_text(err)
            chat_log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=user_input.agent_id,
                    content=text,
                )
            )

        return conversation.async_get_result_from_chat_log(user_input, chat_log)


def _log_request_failure(
    err: BaseException,
    *,
    stage: str,
    retry: str = "none",
    reauth: str = "none",
    level: int = logging.ERROR,
) -> None:
    """Log the innermost integration location without formatting exception details."""
    location = "unknown"
    traceback = err.__traceback__
    while traceback is not None:
        filename = Path(traceback.tb_frame.f_code.co_filename)
        if filename.parent == _INTEGRATION_DIRECTORY:
            location = f"{filename.name}:{traceback.tb_lineno}"
        traceback = traceback.tb_next
    LOGGER.log(
        level,
        "Codex Assist failure: stage=%s exception=%s retry=%s reauth=%s location=%s",
        stage, type(err).__name__, retry, reauth, location,
    )


def _request_failure_text(err: BaseException) -> str:
    """Choose fixed conversation speech without exposing exception details."""
    if isinstance(err, CodexRateLimitError):
        return "Codex Assist cannot process this request because of an account or usage limit."
    return "Sorry, I couldn't complete that."


async def _run_tool_rounds(
    *,
    max_tool_rounds: int,
    run_iteration: Callable[[int, bool], Awaitable[bool]],
) -> None:
    """Run bounded tool rounds, then exactly one tools-disabled final turn."""
    for round_number in range(1, max_tool_rounds + 1):
        if not await run_iteration(round_number, True):
            return
    LOGGER.info(
        "Codex Assist exhausted %d tool-capable rounds; forcing final synthesis",
        max_tool_rounds,
    )
    await run_iteration(max_tool_rounds + 1, False)


async def _stream_codex_turn_into_chat_log(
    *,
    chat_log: conversation.ChatLog,
    codex: CodexClient,
    entity_id: str,
    model: str,
    instructions: str,
    input_items: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    reasoning_effort: str,
    reasoning_summary: str,
    text_verbosity: str,
    text_format: dict[str, Any] | None = None,
    allow_tools: bool = True,
) -> bool:
    tool_call_requested = False

    def mark_tool_call_requested() -> None:
        nonlocal tool_call_requested
        tool_call_requested = True

    async for _delta in chat_log.async_add_delta_content_stream(
        entity_id,
        _codex_stream_to_assistant_deltas(
            codex.stream_turn(
                model=model,
                instructions=instructions,
                input_items=input_items,
                tools=tools,
                reasoning_effort=reasoning_effort,
                reasoning_summary=reasoning_summary,
                text_verbosity=text_verbosity,
                text_format=text_format,
            ),
            on_tool_call=mark_tool_call_requested,
            allow_tools=allow_tools,
        ),
    ):
        pass
    return tool_call_requested


async def _codex_stream_to_assistant_deltas(
    stream: AsyncIterator[CodexStreamDelta],
    *,
    on_tool_call: Callable[[], None] | None = None,
    allow_tools: bool = True,
) -> AsyncIterator[AssistantContentDeltaDict]:
    started = False
    has_answer = False
    has_tool_handoff = False
    response_items: list[dict[str, Any]] = []
    try:
        async for delta in stream:
            if isinstance(delta, CodexResponseItemDelta):
                response_items.append(delta.item)
                continue
            if not started:
                yield {"role": "assistant"}
                started = True
            if isinstance(delta, CodexTextDelta):
                has_answer = has_answer or bool(delta.text.strip())
                yield {"content": delta.text}
            elif isinstance(delta, CodexToolCallDelta):
                if not allow_tools:
                    raise RuntimeError(
                        "Codex Assist final synthesis returned a tool call while tools are disabled"
                    )
                has_tool_handoff = True
                if on_tool_call is not None:
                    on_tool_call()
                yield {
                    "tool_calls": [
                        llm.ToolInput(
                            id=delta.tool_call.id,
                            tool_name=delta.tool_call.name,
                            tool_args=delta.tool_call.arguments,
                        )
                    ]
                }
    except CodexAuthenticationError as err:
        if started:
            err.retry_allowed = False
        raise
    if not has_answer and not has_tool_handoff:
        raise RuntimeError("Codex returned no answer text")
    if native_state := native_state_from_response_items(response_items):
        if not started:
            yield {"role": "assistant"}
        yield {"native": native_state}


async def _refresh_runtime_tokens(
    hass: HomeAssistant,
    entry: ConfigEntry,
    auth_client: CodexAuthClient,
    tokens: CodexTokenSet,
) -> CodexTokenSet:
    return await runtime_token_coordinator(entry).refresh_after_rejection(
        lambda: entry.data,
        rejected_tokens=tokens,
        auth_client=auth_client,
        async_update_entry_data=lambda data: hass.config_entries.async_update_entry(
            entry,
            data=data,
        ),
    )


def _start_reauth_result(
    hass: HomeAssistant,
    entry: ConfigEntry,
    response: intent.IntentResponse,
    user_input: conversation.ConversationInput,
) -> conversation.ConversationResult:
    entry.async_start_reauth(hass)
    response.async_set_speech(_AUTH_FAILURE_TEXT)
    return conversation.ConversationResult(
        response=response,
        conversation_id=user_input.conversation_id,
    )


def _instructions_from_chat_log(
    chat_log: conversation.ChatLog,
    fallback_prompt: str,
) -> str:
    # HA may retain prior system messages when a conversation switches agents;
    # use the context just added for this request, not another agent's prompt.
    for content in reversed(chat_log.content):
        if getattr(content, "role", None) == "system" and isinstance(
            getattr(content, "content", None),
            str,
        ):
            return content.content
    return fallback_prompt


def _instructions_for_turn(
    chat_log: conversation.ChatLog,
    fallback_prompt: str,
    *,
    web_search: bool,
) -> str:
    instructions = _instructions_from_chat_log(chat_log, fallback_prompt)
    instructions = f"{instructions.rstrip()}\n\n{_ERROR_RESPONSE_INSTRUCTIONS}"
    instructions = f"{instructions}\n\n{_CLARIFICATION_INSTRUCTIONS}"
    if not web_search:
        return instructions
    return f"{instructions.rstrip()}\n\n{_WEB_SEARCH_SPEECH_INSTRUCTIONS}"


async def _codex_input_from_chat_log(
    hass: HomeAssistant,
    chat_log: conversation.ChatLog,
    active_agent_id: str | None = None,
    history_boundary: Any = None,
    request_turn: Any = None,
) -> list[dict[str, Any]]:
    input_items: list[dict[str, Any]] = []
    attachments_by_item: dict[int, Any] = {}
    available = scoped_contents(chat_log.content, history_boundary, request_turn)
    contents = (
        _chat_log_contents_for_agent(available, active_agent_id)
        if active_agent_id is not None
        else available
    )
    for content in contents:
        role = getattr(content, "role", None)
        text = getattr(content, "content", None)
        if role == "system":
            continue
        if role == "tool_result":
            # HA 2026.10 wraps tool data in ToolResult; older versions expose it directly.
            result = getattr(content, "result", None)
            tool_data = result.data if result is not None else content.tool_result
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": content.tool_call_id,
                    "output": json_dumps(tool_data),
                }
            )
            continue
        native = getattr(content, "native", None)
        if role == "assistant" and isinstance(native, CodexNativeState):
            input_items.extend(native.items)
            continue
        if role in {"user", "assistant"} and isinstance(text, str) and text.strip():
            item: dict[str, Any] = {"role": role, "content": text}
            input_items.append(item)
            if role == "user":
                attachments_by_item[id(item)] = getattr(content, "attachments", None)

        tool_calls = getattr(content, "tool_calls", None)
        if role == "assistant" and tool_calls:
            for tool_call in tool_calls:
                input_items.append(
                    {
                        "type": "function_call",
                        "name": tool_call.tool_name,
                        "arguments": json_dumps(tool_call.tool_args),
                        "call_id": tool_call.id,
                    }
                )

    retained = _trim_codex_input_items(input_items, max_items=24)
    for item in retained:
        if id(item) in attachments_by_item:
            images = await _async_image_attachments_for_codex(hass, attachments_by_item[id(item)])
            item["content"] = codex_user_content_with_images(item["content"], images)
    return retained


def _chat_log_contents_for_agent(contents: list[Any], agent_id: str) -> list[Any]:
    """Keep whole turns for one agent and the current unanswered user turn."""
    turns: list[tuple[str | None, list[Any]]] = []
    current_turn: list[Any] = []
    current_agent_id: str | None = None

    def finish_turn() -> None:
        if current_turn:
            turns.append((current_agent_id, current_turn.copy()))

    for content in contents:
        role = getattr(content, "role", None)
        if role == "system":
            continue
        if role == "user":
            finish_turn()
            current_turn = [content]
            current_agent_id = None
            continue
        if not current_turn:
            continue
        current_turn.append(content)
        turn_agent_id = getattr(content, "agent_id", None)
        if current_agent_id is None and isinstance(turn_agent_id, str):
            current_agent_id = turn_agent_id

    if current_turn:
        turns.append((current_agent_id, current_turn))

    selected: list[Any] = []
    for index, (turn_agent_id, turn_contents) in enumerate(turns):
        if str(getattr(turn_contents[0], "content", "")).startswith(WIRE_PREFIX):
            # Rejected/unsupported packets can remain in HA logs, but may not
            # leak into a later model turn after pairing is changed/disabled.
            continue
        is_current_unanswered_turn = (
            index == len(turns) - 1
            and turn_agent_id is None
            and getattr(turn_contents[0], "role", None) == "user"
        )
        if turn_agent_id == agent_id or is_current_unanswered_turn:
            selected.extend(turn_contents)
    return selected


def _codex_session_id_for_profile(
    entry_id: str, profile: AgentProfile, speaker_scope: str | None = None
) -> str:
    """Keep the legacy session for the primary agent; isolate added personalities."""
    if speaker_scope is not None:
        return codex_session_id(f"{entry_id}:{profile.agent_id}:{speaker_scope}")
    if profile.agent_id == PRIMARY_AGENT_ID:
        return codex_session_id(entry_id)
    return codex_session_id(f"{entry_id}:{profile.agent_id}")


def _trim_codex_input_items(
    input_items: list[dict[str, Any]],
    *,
    max_items: int,
) -> list[dict[str, Any]]:
    if len(input_items) <= max_items:
        return input_items

    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for item in input_items:
        if item.get("role") == "user" and current:
            groups.append(current)
            current = []
        current.append(item)
    if current:
        groups.append(current)

    selected: list[list[dict[str, Any]]] = []
    selected_items = 0
    for group in reversed(groups):
        if not selected and len(group) > max_items:
            raise ValueError(
                f"Current Codex turn contains {len(group)} items; maximum is {max_items}"
            )
        if selected and selected_items + len(group) > max_items:
            break
        selected.append(group)
        selected_items += len(group)
    return [item for group in reversed(selected) for item in group]


async def _async_image_attachments_for_codex(
    hass: HomeAssistant,
    attachments: Any,
) -> list[tuple[str, bytes]]:
    if not attachments:
        return []
    return await hass.async_add_executor_job(_image_attachments_for_codex, attachments)


def _image_attachments_for_codex(attachments: Any) -> list[tuple[str, bytes]]:
    candidates: list[tuple[str, Any, int]] = []
    for attachment in attachments:
        mime_type = getattr(attachment, "mime_type", "")
        if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
            continue
        path = getattr(attachment, "path", None)
        if path is None:
            raise ValueError("Codex Assist could not read an image attachment")
        try:
            size = path.stat().st_size
        except OSError:
            raise ValueError("Codex Assist could not read an image attachment") from None
        if size > MAX_IMAGE_ATTACHMENT_BYTES:
            raise ValueError("Codex Assist image attachment exceeds the 10 MiB per-file limit")
        candidates.append((mime_type, path, size))

    if len(candidates) > MAX_IMAGE_ATTACHMENTS:
        raise ValueError(f"Codex Assist accepts at most {MAX_IMAGE_ATTACHMENTS} image attachments")
    if sum(size for _, _, size in candidates) > MAX_TOTAL_IMAGE_ATTACHMENT_BYTES:
        raise ValueError("Codex Assist image attachments exceed the total attachment size limit")

    images: list[tuple[str, bytes]] = []
    total_bytes = 0
    for mime_type, path, _size in candidates:
        remaining_bytes = MAX_TOTAL_IMAGE_ATTACHMENT_BYTES - total_bytes
        read_limit = min(MAX_IMAGE_ATTACHMENT_BYTES, remaining_bytes)
        try:
            with path.open("rb") as attachment_file:
                data = attachment_file.read(read_limit + 1)
        except OSError:
            raise ValueError("Codex Assist could not read an image attachment") from None
        if len(data) > MAX_IMAGE_ATTACHMENT_BYTES:
            raise ValueError("Codex Assist image attachment grew beyond the per-file size limit")
        if len(data) > remaining_bytes:
            raise ValueError(
                "Codex Assist image attachments exceed the total attachment size limit"
            )
        total_bytes += len(data)
        images.append((mime_type, data))
    return images


def _codex_tools_from_chat_log(
    chat_log: conversation.ChatLog,
    *,
    enable_web_search: bool = False,
) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    if chat_log.llm_api:
        tools.extend(
            _codex_tool_from_ha_tool(tool, chat_log.llm_api.custom_serializer)
            for tool in chat_log.llm_api.tools
        )
    if enable_web_search:
        search: dict[str, Any] = {"type": "web_search"}
        # Search results follow the home country; codex_client runs search on alpha/search.
        country = getattr(getattr(getattr(chat_log, "hass", None), "config", None), "country", None)
        if isinstance(country, str) and country:
            search["user_location"] = {"type": "approximate", "country": country}
        tools.append(search)
    return tools


def _codex_tool_from_ha_tool(
    tool: llm.Tool,
    custom_serializer: Any,
) -> dict[str, Any]:
    schema = to_openapi(tool.parameters, custom_serializer=custom_serializer)
    unsupported_keys = {"oneOf", "anyOf", "allOf", "enum", "not"}
    if unsupported_keys.intersection(schema):
        schema = {k: v for k, v in schema.items() if k not in unsupported_keys}

    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": schema,
        "strict": False,
    }
