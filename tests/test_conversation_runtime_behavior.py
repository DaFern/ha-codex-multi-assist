from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.codex_assist.codex_auth import CodexAuthTemporaryError, CodexTokenSet
from custom_components.codex_assist.codex_client import CodexRateLimitError
from tests.ha_fakes import install_homeassistant_fakes


class FakeAuthClient:
    async def refresh(self, tokens):
        assert tokens == CodexTokenSet("access-1", "refresh-1")
        return CodexTokenSet("access-2", "refresh-2")


class FakeConfigEntries:
    def __init__(self):
        self.updates = []

    def async_update_entry(self, entry, *, data):
        self.updates.append((entry, data))
        entry.data = data


class FakeEntry:
    def __init__(self):
        self.entry_id = "entry-1"
        self.data = {
            "model": "gpt-5.4",
            "access_token": "access-1",
            "refresh_token": "refresh-1",
        }
        self.reauth_started = False

    def async_start_reauth(self, hass):
        self.reauth_started = True
        self.reauth_hass = hass


class FakeUserInput:
    language = "en"
    conversation_id = "conversation-1"
    agent_id = "conversation.codex_assist"
    extra_system_prompt = None
    context = SimpleNamespace(user_id=None)

    def as_llm_context(self, domain):
        return {"domain": domain}


class FakeHandleMessageChatLog:
    def __init__(self):
        self.content = []
        self.added = []
        self.llm_api = None

    async def async_provide_llm_data(self, *args):
        self.provided_args = args

    def async_add_assistant_content_without_tools(self, content):
        self.added.append(content)


@pytest.fixture
def conversation_module(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    module = importlib.import_module("custom_components.codex_assist.conversation")
    return importlib.reload(module)


@pytest.mark.asyncio
async def test_refresh_runtime_tokens_persists_rotated_tokens(conversation_module):
    hass = type("Hass", (), {"config_entries": FakeConfigEntries()})()
    entry = FakeEntry()

    tokens = await conversation_module._refresh_runtime_tokens(
        hass,
        entry,
        FakeAuthClient(),
        CodexTokenSet("access-1", "refresh-1"),
    )

    assert tokens == CodexTokenSet("access-2", "refresh-2")
    assert hass.config_entries.updates == [
        (
            entry,
            {
                "model": "gpt-5.4",
                "access_token": "access-2",
                "refresh_token": "refresh-2",
            },
        )
    ]


def test_start_reauth_result_starts_ha_reauth_and_returns_user_message(
    conversation_module,
):
    hass = object()
    entry = FakeEntry()
    response = conversation_module.intent.IntentResponse(language="en")

    result = conversation_module._start_reauth_result(
        hass,
        entry,
        response,
        FakeUserInput(),
    )

    assert entry.reauth_started is True
    assert entry.reauth_hass is hass
    assert result.conversation_id == "conversation-1"
    assert response.speech == "Codex Assist needs attention in Home Assistant."


def test_agent_history_keeps_only_same_agent_turns_and_current_user_turn(
    conversation_module,
):
    content = [
        SimpleNamespace(role="system", content="system"),
        SimpleNamespace(role="user", content="old A"),
        SimpleNamespace(role="assistant", agent_id="conversation.agent_a", content="reply A"),
        SimpleNamespace(role="tool_result", agent_id="conversation.agent_a"),
        SimpleNamespace(role="user", content="old B"),
        SimpleNamespace(role="assistant", agent_id="conversation.agent_b", content="reply B"),
        SimpleNamespace(role="user", content="current A"),
    ]

    selected = conversation_module._chat_log_contents_for_agent(
        content, "conversation.agent_a"
    )

    assert [item.content for item in selected if hasattr(item, "content")] == [
        "old A",
        "reply A",
        "current A",
    ]
    assert all(item is not content[4] and item is not content[5] for item in selected)


def test_rejected_wire_packets_never_enter_later_model_history(conversation_module):
    contents = [
        SimpleNamespace(role="user", content="[[voice-match:v2:bad]]\nrejected"),
        SimpleNamespace(role="assistant", agent_id="agent", content="pairing error"),
        SimpleNamespace(role="user", content="normal request"),
    ]
    selected = conversation_module._chat_log_contents_for_agent(contents, "agent")
    assert [item.content for item in selected] == ["normal request"]


def test_agent_profiles_keep_legacy_identity_and_isolate_codex_sessions(
    conversation_module,
):
    entry = FakeEntry()
    entry.options = {
        "prompt": "Legacy Ziggy prompt",
        "model": "legacy-model",
        "reasoning_effort": "high",
        "text_verbosity": "low",
        "web_search": True,
    }
    profiles = conversation_module.get_agent_profiles(entry)

    assert [profile.name for profile in profiles] == [
        "Codex Assist",
        "JARVIS",
        "F.R.I.D.A.Y.",
        "Ultron",
    ]
    assert conversation_module._codex_session_id_for_profile(
        entry.entry_id, profiles[0]
    ) == conversation_module.codex_session_id(entry.entry_id)
    assert profiles[0].prompt == "Legacy Ziggy prompt"
    assert profiles[0].model == "legacy-model"
    assert profiles[0].reasoning_effort == "high"
    assert profiles[0].text_verbosity == "low"
    assert profiles[0].web_search is True
    entities = [
        conversation_module.CodexAssistConversationEntity(entry, profile)
        for profile in profiles
    ]
    assert entities[0]._attr_unique_id == entry.entry_id
    assert len({entity._attr_unique_id for entity in entities}) == len(entities)
    assert len(
        {
            conversation_module._codex_session_id_for_profile(entry.entry_id, profile)
            for profile in profiles
        }
    ) == len(profiles)


def test_saved_primary_prompt_is_independent_from_ai_task_prompt(conversation_module):
    entry = FakeEntry()
    entry.options = {
        "prompt": "Updated AI Task instructions",
        "agents": [
            {
                "id": "primary",
                "name": "Codex Assist",
                "prompt": "Saved primary conversation instructions",
                "model": "gpt-5.4",
            }
        ],
    }

    profiles = conversation_module.get_agent_profiles(entry)

    assert len(profiles) == 1
    assert profiles[0].prompt == "Saved primary conversation instructions"


@pytest.mark.asyncio
async def test_handle_message_reports_temporary_auth_failure_without_reauth(
    conversation_module,
    monkeypatch,
):
    async def fail_temporarily(*args, **kwargs):
        raise CodexAuthTemporaryError("rate limited")

    hass = type(
        "Hass",
        (),
        {"http_client": None, "config_entries": FakeConfigEntries()},
    )()
    entry = FakeEntry()
    entry.options = {}
    entity = conversation_module.CodexAssistConversationEntity(entry)
    entity.hass = hass
    chat_log = FakeHandleMessageChatLog()

    class FailingCoordinator:
        async def resolve(self, *args, **kwargs):
            return await fail_temporarily()

    monkeypatch.setattr(
        conversation_module,
        "runtime_token_coordinator",
        lambda entry: FailingCoordinator(),
    )

    result = await entity._async_handle_message(FakeUserInput(), chat_log)

    assert entry.reauth_started is False
    assert result[1] is chat_log
    assert len(chat_log.added) == 1
    assert chat_log.added[0].content == "Sorry, I couldn't complete that."


@pytest.mark.asyncio
async def test_handle_message_reports_friendly_usage_limit_without_status_code(
    conversation_module,
    monkeypatch,
):
    async def resolve_tokens(*args, **kwargs):
        return CodexTokenSet("access-1", "refresh-1")

    async def raise_rate_limit(*args, **kwargs):
        raise CodexRateLimitError("Codex usage limit or rate limit reached: quota exceeded")

    hass = type(
        "Hass",
        (),
        {"http_client": None, "config_entries": FakeConfigEntries()},
    )()
    entry = FakeEntry()
    entry.options = {}
    entity = conversation_module.CodexAssistConversationEntity(entry)
    entity.hass = hass
    entity.entity_id = "conversation.codex_assist"
    chat_log = FakeHandleMessageChatLog()

    class ResolvedCoordinator:
        async def resolve(self, *args, **kwargs):
            return await resolve_tokens()

    monkeypatch.setattr(
        conversation_module,
        "runtime_token_coordinator",
        lambda entry: ResolvedCoordinator(),
    )
    monkeypatch.setattr(
        conversation_module,
        "_stream_codex_turn_into_chat_log",
        raise_rate_limit,
    )

    result = await entity._async_handle_message(FakeUserInput(), chat_log)

    assert result[1] is chat_log
    assert len(chat_log.added) == 1
    assert chat_log.added[0].content == (
        "Codex Assist cannot process this request because of an account or usage limit."
    )
    assert "status 429" not in chat_log.added[0].content
    assert "Codex request failed" not in chat_log.added[0].content


@pytest.mark.asyncio
async def test_paired_preferences_reach_only_this_turn_without_impersonating_user(
    conversation_module, monkeypatch,
):
    from cryptography.fernet import Fernet

    from custom_components.codex_assist.speaker_packet import encode

    key = Fernet.generate_key().decode()
    entry = FakeEntry()
    entry.options = {"voice_match_pairing_key": key}
    entity = conversation_module.CodexAssistConversationEntity(entry)
    entity.hass = type("Hass", (), {
        "http_client": None, "config_entries": FakeConfigEntries(), "data": {},
        "auth": SimpleNamespace(async_get_user=AsyncMock(return_value=SimpleNamespace(
            id="actual-ha-caller", is_active=True, system_generated=False,
        ))),
    })()
    entity.entity_id = "conversation.codex_assist"
    user_input = FakeUserInput()
    user_input.context = SimpleNamespace(user_id="actual-ha-caller")
    user_input.text = encode(key, "hello", voice="alice", revision="a" * 32,
                             instructions="Be brief. {{ states('private') }}",
                             ha_user_id="actual-ha-caller")
    chat_log = FakeHandleMessageChatLog()
    chat_log.content = [SimpleNamespace(role="system", content="Rendered base personality"),
                        SimpleNamespace(role="user", content="Old unrelated private turn"),
                        SimpleNamespace(role="user", content=user_input.text)]
    class Coordinator:
        async def resolve(self, *args, **kwargs):
            return CodexTokenSet("access-1", "refresh-1")
    seen = {}
    async def capture(**kwargs):
        seen.update(kwargs)
        return False
    monkeypatch.setattr(
        conversation_module, "runtime_token_coordinator", lambda entry: Coordinator()
    )
    monkeypatch.setattr(conversation_module, "_stream_codex_turn_into_chat_log", capture)
    result = await entity._async_handle_message(user_input, chat_log)
    assert seen["instructions"].startswith("Rendered base personality")
    assert "Be brief. {{ states('private') }}" in seen["instructions"]
    assert [item["content"] for item in seen["input_items"]] == ["hello"]
    assert result[0].context is user_input.context
    assert result[0].context.user_id == "actual-ha-caller"
    assert result[0].text == "hello"
    assert "Be brief" not in chat_log.provided_args[2]


@pytest.mark.asyncio
async def test_voice_account_mismatch_strips_private_context_and_disables_tools(
    conversation_module, monkeypatch,
):
    from cryptography.fernet import Fernet

    from custom_components.codex_assist.speaker_packet import encode

    key = Fernet.generate_key().decode()
    entry = FakeEntry()
    entry.options = {"voice_match_pairing_key": key}
    entity = conversation_module.CodexAssistConversationEntity(entry)
    entity.hass = type("Hass", (), {
        "http_client": None, "config_entries": FakeConfigEntries(), "data": {},
        "auth": SimpleNamespace(async_get_user=AsyncMock(return_value=SimpleNamespace(
            id="profile-owner", is_active=True, system_generated=False,
        ))),
    })()
    entity.entity_id = "conversation.codex_assist"
    user_input = FakeUserInput()
    user_input.context = SimpleNamespace(user_id="different-ha-caller")
    user_input.text = encode(
        key, "hello", voice="alice", revision="a" * 32,
        instructions="Private profile instruction", speaker_name="Private profile name",
        ha_user_id="profile-owner",
    )
    context = user_input.context
    chat_log = FakeHandleMessageChatLog()
    chat_log.content = [
        SimpleNamespace(role="system", content="Rendered base personality"),
        SimpleNamespace(role="user", content="Old private account turn"),
        SimpleNamespace(role="user", content=user_input.text),
    ]

    class Coordinator:
        async def resolve(self, *args, **kwargs):
            return CodexTokenSet("access-1", "refresh-1")

    seen = {}

    async def capture(**kwargs):
        seen.update(kwargs)
        return False

    monkeypatch.setattr(
        conversation_module, "runtime_token_coordinator", lambda entry: Coordinator(),
    )
    monkeypatch.setattr(conversation_module, "_stream_codex_turn_into_chat_log", capture)
    result = await entity._async_handle_message(user_input, chat_log)

    assert result[0].context is context
    assert "Private profile instruction" not in seen["instructions"]
    assert "Private profile name" not in seen["instructions"]
    assert "Do not claim to have read or changed any Home Assistant state" in seen["instructions"]
    assert [item["content"] for item in seen["input_items"]] == ["hello"]
    assert seen["tools"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_history", [False, True])
async def test_neutral_voice_followup_continues_only_ordinary_dialogue_without_tools(
    conversation_module, monkeypatch, tool_history,
):
    from cryptography.fernet import Fernet

    from custom_components.codex_assist.speaker_packet import encode
    from custom_components.codex_assist.voice_match import runtime_for_entry

    key = Fernet.generate_key().decode()
    entry = FakeEntry()
    entry.options = {"voice_match_pairing_key": key}
    entity = conversation_module.CodexAssistConversationEntity(entry)
    entity.hass = SimpleNamespace(
        http_client=None, config_entries=FakeConfigEntries(), data={},
        auth=SimpleNamespace(async_get_user=AsyncMock(return_value=SimpleNamespace(
            id="caller", is_active=True, system_generated=False,
        ))),
    )
    entity.entity_id = "conversation.codex_assist"
    user_input = FakeUserInput()
    user_input.context = SimpleNamespace(user_id="caller")
    first = encode(key, "Help with a calendar", voice="alice", revision="a" * 32,
                   ha_user_id="caller", instructions="Earlier private preference")
    chat_log = FakeHandleMessageChatLog()
    chat_log.content = [SimpleNamespace(role="system", content="Rendered personality"),
                        SimpleNamespace(role="user", content=first)]
    runtime_for_entry(entry).prepare_request(
        key, first, chat_log.content, user_input.conversation_id, user_input.agent_id,
    )
    if tool_history:
        chat_log.content.append(SimpleNamespace(role="tool_result", content="Private events"))
    chat_log.content.append(SimpleNamespace(
        role="assistant", content="Which calendar do you use?", agent_id=user_input.agent_id,
    ))
    user_input.text = encode(key, "I use Google")
    chat_log.content.append(SimpleNamespace(role="user", content=user_input.text))

    class Coordinator:
        async def resolve(self, *args, **kwargs):
            return CodexTokenSet("access-1", "refresh-1")

    seen = {}

    async def capture(**kwargs):
        seen.update(kwargs)
        return False

    native = AsyncMock(return_value=None)
    monkeypatch.setattr(conversation_module, "async_native_request", native)
    monkeypatch.setattr(
        conversation_module, "runtime_token_coordinator", lambda entry: Coordinator(),
    )
    monkeypatch.setattr(conversation_module, "_stream_codex_turn_into_chat_log", capture)
    await entity._async_handle_message(user_input, chat_log)

    native.assert_awaited_once()
    assert native.call_args.kwargs["allow_execution"] is False
    assert seen["tools"] == [] and seen["allow_tools"] is False
    assert "Earlier private preference" not in seen["instructions"]
    assert "History does not identify" in seen["instructions"]
    expected = (["I use Google"] if tool_history else [
        "Help with a calendar", "Which calendar do you use?", "I use Google",
    ])
    assert [item["content"] for item in seen["input_items"]] == expected
