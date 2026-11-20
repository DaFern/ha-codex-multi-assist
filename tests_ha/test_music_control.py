"""Music API isolation and request-bound tool exposure."""

from types import SimpleNamespace

import pytest
from homeassistant.core import Context, SupportsResponse
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.llm import LLMContext
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist.satellite_runtime import satellite_tools_supported

if not satellite_tools_supported():
    pytest.skip("Music tools require HA's modern native tool contract", allow_module_level=True)

from custom_components.codex_assist.action_control import action_outcome
from custom_components.codex_assist.music_api import MusicControlAPI
from custom_components.codex_assist.music_control import (
    MusicAuthorization,
    MusicControlTool,
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


def _outcome(result, call_id="music"):
    """Use the conversation loop's real current-round result classifier."""
    return action_outcome([
        SimpleNamespace(role="assistant", tool_calls=[
            SimpleNamespace(id=call_id, tool_name=MusicControlTool.name, external=False),
        ]),
        SimpleNamespace(role="tool_result", tool_call_id=call_id, result=result),
    ])


@pytest.fixture
def music_request(hass, hass_admin_user, monkeypatch):
    from custom_components.codex_assist import music_control

    context = Context(user_id="original-caller")
    entry = MockConfigEntry(domain="music_assistant")
    entry.add_to_hass(hass)
    player = er.async_get(hass).async_get_or_create(
        "media_player", "music_assistant", "test-music",
        suggested_object_id="test_music", config_entry=entry,
    )
    hass.states.async_set(player.entity_id, "idle")
    monkeypatch.setattr(music_control, "async_should_expose", lambda *args: True)
    authorization = MusicAuthorization(
        context=context,
        prepared_request=PreparedRequest(
            "play music", "", object(), None, verified=True, voice="test-voice",
            ha_user_id=hass_admin_user.id,
        ),
        user_id=hass_admin_user.id,
        player_ids=(player.entity_id,),
        satellite_id=None,
        device_id=None,
    )
    tool = MusicControlTool(authorization)

    async def invoke(**args):
        return await tool.async_call(
            hass, SimpleNamespace(tool_args={"speaker": player.entity_id, **args}),
            _context(context),
        )

    return authorization, tool, invoke


@pytest.mark.parametrize("args", [
    {"action": "play"},
    {"action": "volume"},
    {"action": "play", "speaker": "Missing speaker"},
])
async def test_clarifications_do_not_acknowledge_actions(hass, music_request, args):
    _, _, invoke = music_request
    result = await invoke(**args)
    assert result.data["status"] == "clarify"
    assert not result.error
    assert _outcome(result).speech is None


async def test_disallowed_target_clarifies_without_acknowledgement(
    hass, music_request, monkeypatch,
):
    _, tool, invoke = music_request
    monkeypatch.setattr(tool, "_target_is_allowed", lambda *args: False)
    result = await invoke(action="resume")
    assert result.data["status"] == "clarify"
    assert _outcome(result).speech is None


@pytest.mark.parametrize("response", [
    {}, {"tracks": []}, {"tracks": [{"name": "Missing URI"}]},
])
async def test_empty_search_does_not_acknowledge_playback(hass, music_request, response):
    _, _, invoke = music_request

    async def search(call):
        return response

    hass.services.async_register(
        "music_assistant", "search", search, supports_response=SupportsResponse.ONLY,
    )
    result = await invoke(action="play", query="Test track")
    assert result.data["status"] == "not_found"
    assert _outcome(result).speech is None


@pytest.mark.parametrize("response,status", [
    (None, "unconfirmed"),
    ({}, "unconfirmed"),
    ({"media_player.test_music": {"items": None}}, "unconfirmed"),
    ({"media_player.test_music": {"items": []}}, "ok"),
    ({"media_player.test_music": {"items": [{"name": "Test track"}]}}, "ok"),
])
async def test_queue_results_are_queries(music_request, response, status):
    auth, tool, _ = music_request
    from homeassistant.helpers import llm

    result = llm.ToolResult(data=tool._queue_result(response, auth.player_ids[0]))
    assert result.data["status"] == status
    assert _outcome(result).speech is None


@pytest.mark.parametrize("revoke", [False, True])
async def test_search_continues_to_playback_with_rechecks_and_no_duplicate(
    hass, music_request, monkeypatch, revoke,
):
    """Simulate successive model choices using real services and the loop's gate."""
    auth, tool, invoke = music_request
    calls = []

    async def search(call):
        calls.append(call)
        return {"tracks": [{"uri": "library://track/1", "name": "Test track",
                            "media_type": "track"}]}

    async def play(call):
        calls.append(call)

    hass.services.async_register(
        "music_assistant", "search", search, supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register("music_assistant", "play_media", play)
    result = await invoke(action="play", query="Test track")
    assert result.data["status"] == "selection_required"
    # This is the gate that previously ended the conversation before playback.
    assert _outcome(result).speech is None
    assert [call.service for call in calls] == ["search"]
    candidate_id = result.data["results"][0]["candidate_id"]
    if revoke:
        assert_allowed = tool._assert_allowed

        async def revoke_before_admission(*args):
            hass.states.async_set(auth.player_ids[0], "unavailable")
            return await assert_allowed(*args)

        monkeypatch.setattr(tool, "_assert_allowed", revoke_before_admission)
    result = await invoke(action="play", candidate_id=candidate_id)
    assert _outcome(result).kind == ("failed" if revoke else "accepted")
    assert [call.service for call in calls] == (
        ["search"] if revoke else ["search", "play_media"]
    )
    assert all(call.context is auth.context for call in calls)
    assert auth.context.user_id == "original-caller"
    if not revoke:
        replay = await invoke(action="play", candidate_id=candidate_id)
        assert replay.error
        assert _outcome(replay).kind == "failed"
        assert len(calls) == 2


async def test_failed_search_is_still_an_error(hass, music_request):
    _, _, invoke = music_request

    async def search(call):
        return None

    hass.services.async_register(
        "music_assistant", "search", search, supports_response=SupportsResponse.ONLY,
    )
    result = await invoke(action="play", query="Test track")
    assert result.error
    assert _outcome(result).kind == "failed"


@pytest.mark.parametrize("action,service", [
    ("resume", "media_play"), ("pause", "media_pause"), ("volume", "volume_set"),
    ("clear_queue", "clear_playlist"),
])
async def test_actual_player_commands_still_acknowledge_after_admission(
    hass, music_request, action, service,
):
    auth, _, invoke = music_request
    calls = []

    async def handler(call):
        calls.append(call)

    hass.services.async_register("media_player", service, handler)
    result = await invoke(action=action, level=30)
    assert _outcome(result).kind == "accepted"
    assert len(calls) == 1
    assert calls[0].context is auth.context


async def test_real_conversation_search_reaches_playback_before_acknowledgement(
    hass, hass_admin_user, music_request, monkeypatch,
):
    """Stub the model only; let HA's ChatLog execute tools and loop normally."""
    import json

    from cryptography.fernet import Fernet
    from homeassistant.components import conversation
    from homeassistant.setup import async_setup_component

    from custom_components.codex_assist import DOMAIN
    from custom_components.codex_assist.codex_client import (
        CodexClient,
        CodexTextDelta,
        CodexToolCall,
        CodexToolCallDelta,
    )
    from custom_components.codex_assist.speaker_packet import encode

    auth, _, _ = music_request
    player_id = auth.player_ids[0]
    satellite = er.async_get(hass).async_get_or_create(
        "assist_satellite", "test", "test-satellite",
    )
    key = Fernet.generate_key().decode()
    assert await async_setup_component(hass, "homeassistant", {})
    entry = MockConfigEntry(
        domain=DOMAIN, title="Codex Assist", unique_id=DOMAIN,
        data={"access_token": "test-only", "refresh_token": "test-only", "model": "gpt-5.4"},
        options={"voice_match_pairing_key": key, "music_player_ids": [player_id]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    services = []
    model_rounds = []

    async def search(call):
        services.append(call)
        return {"tracks": [{"uri": "library://track/1", "name": "Test track",
                            "media_type": "track"}]}

    async def play(call):
        services.append(call)

    hass.services.async_register(
        "music_assistant", "search", search, supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register("music_assistant", "play_media", play)

    async def reply(self, **kwargs):
        model_rounds.append(kwargs)
        if len(model_rounds) == 1:
            music_name = next(
                tool["name"] for tool in kwargs["tools"]
                if tool["name"].endswith("music_control")
            )
            yield CodexToolCallDelta(CodexToolCall(
                "search", music_name,
                {"action": "play", "query": "Test track", "speaker": player_id},
            ))
        elif len(model_rounds) == 2:
            assert [call.service for call in services] == ["search"]
            outputs = [item for item in kwargs["input_items"]
                       if item.get("type") == "function_call_output"]
            selection = json.loads(outputs[-1]["output"])
            music_name = next(
                tool["name"] for tool in kwargs["tools"]
                if tool["name"].endswith("music_control")
            )
            yield CodexToolCallDelta(CodexToolCall(
                "play", music_name,
                {"action": "play", "speaker": player_id,
                 "candidate_id": selection["results"][0]["candidate_id"]},
            ))
        else:
            assert [call.service for call in services] == ["search", "play_media"]
            yield CodexTextDelta(json.dumps({
                "outcome": "accepted", "reply": "The playback command was accepted.",
            }))

    monkeypatch.setattr(CodexClient, "stream_turn", reply)
    wire = encode(
        key, "Play Test track", voice="test-voice", revision="a" * 32,
        ha_user_id=hass_admin_user.id,
    )
    context = Context(user_id=hass_admin_user.id)
    result = await conversation.async_converse(
        hass, wire, None, context, agent_id="conversation.codex_assist",
        satellite_id=satellite.entity_id,
    )
    assert [call.service for call in services] == ["search", "play_media"]
    assert all(call.context is context for call in services)
    assert len(model_rounds) == 3
    assert result.response.speech["plain"]["speech"] == "The playback command was accepted."
