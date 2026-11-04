"""Real HA ChatLog/ConversationInput contract, external Codex response stubbed."""

from cryptography.fernet import Fernet
from homeassistant.components import conversation
from homeassistant.core import Context
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist import DOMAIN
from custom_components.codex_assist.codex_client import CodexClient, CodexTextDelta
from custom_components.codex_assist.speaker_packet import encode


async def test_real_chat_log_separates_speakers_and_does_not_render_personal_templates(
    hass, monkeypatch,
):
    key = Fernet.generate_key().decode()
    assert await async_setup_component(hass, "homeassistant", {})
    entry = MockConfigEntry(domain=DOMAIN, title="Codex Assist", unique_id=DOMAIN,
                            data={"access_token": "test-only", "refresh_token": "test-only",
                                  "model": "gpt-5.4"},
                            options={"voice_match_pairing_key": key})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    calls = []

    async def reply(self, **kwargs):
        calls.append(kwargs)
        yield CodexTextDelta("Test reply.")

    monkeypatch.setattr(CodexClient, "stream_turn", reply)
    conversation_id = None
    for voice, instructions in (("alice", "Be brief. {{ 7 * 7 }}"), ("bob", "Be detailed")):
        wire = encode(key, "hello", voice=voice, revision="a" * 32, instructions=instructions)
        result = await conversation.async_converse(
            hass, wire, conversation_id, Context(), agent_id="conversation.codex_assist",
        )
        conversation_id = result.conversation_id
        assert result.response.speech["plain"]["speech"] == "Test reply."
        assert instructions in calls[-1]["instructions"]
        assert [item["content"] for item in calls[-1]["input_items"]] == ["hello"]

    wire = encode(key, "hello")
    await conversation.async_converse(
        hass, wire, conversation_id, Context(), agent_id="conversation.codex_assist",
    )
    assert "Be detailed" not in calls[-1]["instructions"]
    assert [item["content"] for item in calls[-1]["input_items"]] == ["hello"]
    before = len(calls)
    await conversation.async_converse(
        hass, wire, conversation_id, Context(), agent_id="conversation.codex_assist",
    )
    assert len(calls) == before  # Duplicate nonce never reaches the provider.
