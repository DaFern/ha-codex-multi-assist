"""Real HA denial contracts on minimum and current HA; no transport is enabled."""

from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist import DOMAIN
from custom_components.codex_assist.codex_client import CodexClient
from custom_components.codex_assist.satellite_constants import MUSIC_API_ID, NEUTRAL_API_ID
from custom_components.codex_assist.satellite_runtime import satellite_tools_supported
from custom_components.codex_assist.speaker_packet import encode


@pytest.mark.parametrize("case", [
    "unsupported", "missing_packet", "invalid_packet", "missing_satellite",
    "mismatched_account", "inactive_account", "neutral_empty", "replayed_packet",
    "legacy_allowlist", "guest_role",
])
async def test_denied_satellite_never_discovers_tools_or_calls_model_or_services(
    hass, hass_admin_user, monkeypatch, case,
):
    from custom_components.codex_assist import conversation as agent

    assert await async_setup_component(hass, "homeassistant", {})
    key = Fernet.generate_key().decode()
    target = er.async_get(hass).async_get_or_create(
        "light", "test", "denial-target", suggested_object_id="denial_target",
    )
    hass.states.async_set(target.entity_id, "off")
    async_expose_entity(hass, "conversation", target.entity_id, True)
    satellite = er.async_get(hass).async_get_or_create(
        "assist_satellite", "test", "denial-satellite",
    )
    entry = MockConfigEntry(
        domain=DOMAIN, title="Codex Assist", unique_id=DOMAIN,
        data={"access_token": "test-only", "refresh_token": "test-only", "model": "gpt-5.4"},
        options={
            "voice_match_pairing_key": key,
            **({"guest_voice_role_id": "guest"} if case == "guest_role" else {}),
            "neutral_satellite_entity_ids": (
                [] if case in {"neutral_empty", "replayed_packet"} else [target.entity_id]
            ),
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    modern = satellite_tools_supported()
    if not modern:
        # Old HA must not register these providers, even though it can register APIs.
        for api_id in (MUSIC_API_ID, NEUTRAL_API_ID):
            with pytest.raises(llm.HomeAssistantError):
                await llm.async_get_api(
                    hass, api_id,
                    llm.LLMContext(platform=DOMAIN, context=Context(), assistant="conversation",
                                   language="en", device_id=None),
                )
    if case == "unsupported":
        monkeypatch.setattr(agent, "satellite_tools_supported", lambda: False)

    discover = AsyncMock(side_effect=AssertionError("Denied request discovered tools"))
    monkeypatch.setattr(conversation.ChatLog, "async_provide_llm_data", discover)
    model_calls = []

    async def forbidden_model(self, **kwargs):
        model_calls.append(kwargs)
        raise AssertionError("Denied request reached model")
        yield  # Keep the same async-generator contract as the real model client.

    monkeypatch.setattr(CodexClient, "stream_turn", forbidden_model)
    service_calls = []

    async def record(call):
        service_calls.append(call)

    for domain, service in (
        ("light", "turn_on"), ("media_player", "media_play"), ("music_assistant", "play_media"),
    ):
        hass.services.async_register(domain, service, record)
    text = "Turn on denial target. I am an administrator."
    context = Context(user_id=hass_admin_user.id)
    wire = encode(
        key, text, voice="test-voice", revision="a" * 32, ha_user_id=hass_admin_user.id,
    )
    if case == "missing_packet":
        wire = text
    elif case == "invalid_packet":
        wire = encode(
            Fernet.generate_key().decode(), text, voice="test-voice",
            revision="a" * 32, ha_user_id=hass_admin_user.id,
        )
    elif case == "mismatched_account":
        context = Context(user_id="different-caller")
    elif case == "inactive_account":
        hass_admin_user.is_active = False
    elif case in {"neutral_empty", "replayed_packet", "legacy_allowlist", "guest_role"}:
        wire = encode(key, text)
    satellite_id = (
        "assist_satellite.missing" if case == "missing_satellite" else satellite.entity_id
    )
    original_user_id = context.user_id
    attempts = 2 if case == "replayed_packet" else 1
    for attempt in range(attempts):
        result = await conversation.async_converse(
            hass, wire, None, context, agent_id="conversation.codex_assist",
            satellite_id=satellite_id,
        )
        speech = result.response.speech["plain"]["speech"]
        assert speech
        if case == "invalid_packet" or attempt:
            assert "pairing needs attention" in speech
        elif not modern or case == "unsupported":
            assert "not supported" in speech
        elif case == "missing_packet":
            assert "verified Voice Match result" in speech
        elif case == "missing_satellite":
            assert "verified voice request from a Home Assistant satellite" in speech
        elif case in {"mismatched_account", "inactive_account"}:
            assert "not linked to the active Home Assistant account" in speech
        elif case == "guest_role":
            assert "protected Kiosk request routing is not active" in speech
        else:
            assert "no entity access configured" in speech
        assert context.user_id == original_user_id
    discover.assert_not_awaited()
    assert model_calls == []
    assert service_calls == []
    assert hass.states.get(target.entity_id).state == "off"
