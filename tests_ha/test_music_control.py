"""Music API isolation and request-bound tool exposure."""

from types import SimpleNamespace

import pytest
from homeassistant.helpers.llm import LLMContext

from custom_components.codex_assist.music_api import MusicControlAPI
from custom_components.codex_assist.music_control import (
    MusicAuthorization,
    music_authorization,
)
from custom_components.codex_assist.voice_match import PreparedRequest


def _context(context):
    return LLMContext(
        platform="codex_assist",
        context=context,
        language="en",
        assistant="conversation",
        device_id="speaker-device",
    )


@pytest.mark.parametrize("verified,voice,account", [
    (False, "daniel", "linked-user"),
    (True, None, "linked-user"),
    (True, "daniel", None),
])
async def test_music_api_fails_closed_without_verified_linked_voice(
    hass, verified, voice, account
):
    context = SimpleNamespace(user_id="original-user")
    request = PreparedRequest(
        "play music", "", object(), None,
        verified=verified, voice=voice, ha_user_id=account,
    )
    authorization = MusicAuthorization(
        context=context,
        prepared_request=request,
        user_id=account or "",
        player_ids=("media_player.test_music",),
        satellite_id="assist_satellite.test",
        device_id="speaker-device",
    )
    api = MusicControlAPI(hass=hass, id="codex_assist_music", name="Music")

    with music_authorization(authorization):
        instance = await api.async_get_api_instance(_context(context))

    assert instance.tools == []


async def test_music_api_exposes_only_one_tool_for_exact_request_context(hass):
    context = SimpleNamespace(user_id="original-user")
    request = PreparedRequest(
        "play music", "", object(), None,
        verified=True, voice="daniel", ha_user_id="linked-user",
    )
    authorization = MusicAuthorization(
        context=context,
        prepared_request=request,
        user_id="linked-user",
        player_ids=("media_player.test_music",),
        satellite_id="assist_satellite.test",
        device_id="speaker-device",
    )
    api = MusicControlAPI(hass=hass, id="codex_assist_music", name="Music")

    with music_authorization(authorization):
        instance = await api.async_get_api_instance(_context(context))
        wrong_context = await api.async_get_api_instance(
            _context(SimpleNamespace(user_id="linked-user"))
        )

    assert [tool.name for tool in instance.tools] == ["codex_assist__music_control"]
    assert wrong_context.tools == []
    assert context.user_id == "original-user"
