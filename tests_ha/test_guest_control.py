"""Synthetic admission, real HA tools/services; actual RBAC pairing is tested separately."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import Context, SupportsResponse
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist.satellite_runtime import satellite_tools_supported

if not satellite_tools_supported():
    pytest.skip("Guest tools require modern native tool types", allow_module_level=True)

from custom_components.codex_assist import guest_control, music_control
from custom_components.codex_assist.guest_control import (
    GuestAuthorization,
    GuestMusicControlTool,
    GuestOnOffTool,
    async_guest_tools,
)
from custom_components.codex_assist.voice_match import PreparedRequest


@pytest.fixture
def guest(hass, monkeypatch):
    entry = MockConfigEntry(domain="music_assistant")
    entry.add_to_hass(hass)
    for domain in ("light", "switch", "fan", "media_player"):
        entity = er.async_get(hass).async_get_or_create(
            domain, "music_assistant" if domain == "media_player" else "test",
            f"{domain}-guest", suggested_object_id="guest",
            **({"config_entry": entry} if domain == "media_player" else {}),
        )
        hass.states.async_set(entity.entity_id, "off", {"friendly_name": "Guest device"})
    state = SimpleNamespace(
        current=True, role="guest", allowed={"light.guest", "switch.guest", "fan.guest",
                                            "media_player.guest"}, calls=[], checks=[],
    )
    context = Context(user_id="original-kiosk")
    prepared = PreparedRequest("Test request", "", None, None, verified=True)
    auth = GuestAuthorization(
        context, prepared, "guest", "assist_satellite.test",
        request_is_current=lambda ctx, req: state.current and ctx is context and req is prepared,
        selected_role=lambda: state.role,
    )

    async def policy(_hass, role, ids, *, operation="read"):
        state.checks.append((role, ids, operation))
        return role == state.role and set(ids) <= state.allowed

    async def snapshot(_hass, role, ids):
        return [{"entity_id": eid, "name": "Guest device", "state": "off", "attributes": {}}
                for eid in ids if eid in state.allowed]

    monkeypatch.setattr(guest_control, "async_check_guest_action", policy)
    monkeypatch.setattr(guest_control, "async_guest_snapshot", snapshot)
    monkeypatch.setattr(music_control, "async_should_expose", lambda *args: True)

    async def record(call):
        state.calls.append(call)

    for domain, service in (
        ("light", "turn_on"), ("light", "turn_off"), ("switch", "turn_on"),
        ("fan", "turn_on"), ("media_player", "media_play"), ("media_player", "volume_set"),
        ("music_assistant", "play_media"),
    ):
        hass.services.async_register(domain, service, record)
    return SimpleNamespace(auth=auth, context=context, prepared=prepared, state=state)


def llm_context(guest):
    return llm.LLMContext(
        platform="codex_assist", context=guest.context, assistant="conversation",
        language="en", device_id=None,
    )


async def invoke(hass, guest, tool, args):
    return await tool.async_call(
        hass, llm.ToolInput(tool_name=tool.name, tool_args=args), llm_context(guest),
    )


@pytest.mark.parametrize("domain", ["light", "switch", "fan"])
async def test_native_guest_onoff_preserves_original_context_and_rejects_replay(
    hass, guest, domain,
):
    tool = GuestOnOffTool(hass, guest.auth)
    args = {"operation": "turn_on", "entity_ids": [f"{domain}.guest"]}
    result = await invoke(hass, guest, tool, args)
    assert not result.error
    assert len(guest.state.calls) == 1
    assert guest.state.calls[0].context is guest.context
    assert guest.context.user_id == "original-kiosk"
    assert (await invoke(hass, guest, tool, args)).error
    assert len(guest.state.calls) == 1
    assert guest.state.checks == [("guest", (f"{domain}.guest",), "turn_on")] * 2


async def test_guest_mixed_batch_executes_nothing(hass, guest):
    guest.state.allowed.remove("fan.guest")
    result = await invoke(hass, guest, GuestOnOffTool(hass, guest.auth), {
        "operation": "turn_on", "entity_ids": ["switch.guest", "fan.guest"],
    })
    assert result.error
    assert guest.state.calls == []


@pytest.mark.parametrize("change", [
    "matched", "unverified", "supplied_account", "role", "source", "caller", "expired",
])
async def test_invalid_guest_authority_never_calls_services(hass, guest, change):
    auth = guest.auth
    if change == "matched":
        auth = replace(auth, prepared=replace(guest.prepared, voice="recognised"))
    elif change == "unverified":
        auth = replace(auth, prepared=replace(guest.prepared, verified=False))
    elif change == "supplied_account":
        auth = replace(auth, prepared=replace(guest.prepared, ha_user_id="owner"))
    elif change == "role":
        guest.state.role = "other"
    elif change == "source":
        guest.state.current = False
    elif change == "caller":
        guest.context.user_id = "owner"
    else:
        auth = replace(auth, expires=0)
    result = await invoke(hass, guest, GuestOnOffTool(hass, auth), {
        "operation": "turn_on", "entity_ids": ["light.guest"],
    })
    assert result.error
    assert guest.state.calls == []


async def test_revocation_in_native_child_task_is_rechecked(hass, guest, monkeypatch):
    policy = AsyncMock(side_effect=[True, False])
    monkeypatch.setattr(guest_control, "async_check_guest_action", policy)
    result = await invoke(hass, guest, GuestOnOffTool(hass, guest.auth), {
        "operation": "turn_on", "entity_ids": ["light.guest"],
    })
    assert result.error
    assert policy.await_count == 2
    assert guest.state.calls == []


@pytest.mark.parametrize("action", ["resume", "volume"])
async def test_guest_music_fixed_controls_never_resolve_an_ha_user(
    hass, guest, monkeypatch, action,
):
    get_user = AsyncMock(side_effect=AssertionError("Guests must not impersonate an HA user"))
    monkeypatch.setattr(hass.auth, "async_get_user", get_user)
    tool = GuestMusicControlTool(guest.auth, ("media_player.guest",))
    result = await invoke(hass, guest, tool, {
        "action": action, "speaker": "media_player.guest", "level": 25,
    })
    assert not result.error
    assert len(guest.state.calls) == 1
    assert guest.state.calls[0].context is guest.context
    get_user.assert_not_awaited()


async def test_guest_search_can_select_once_without_account_authority(hass, guest):
    async def search(call):
        assert call.context is guest.context
        return {"tracks": [{"uri": "library://track/1", "name": "Test track",
                            "media_type": "track"}]}

    hass.services.async_register(
        "music_assistant", "search", search, supports_response=SupportsResponse.ONLY,
    )
    tool = GuestMusicControlTool(guest.auth, ("media_player.guest",))
    result = await invoke(hass, guest, tool, {
        "action": "play", "query": "Test track", "speaker": "media_player.guest",
    })
    assert result.data["response_type"] == "query_answer"
    args = {"action": "play", "speaker": "media_player.guest",
            "candidate_id": result.data["results"][0]["candidate_id"]}
    assert not (await invoke(hass, guest, tool, args)).error
    assert len(guest.state.calls) == 1
    assert guest.state.calls[0].domain == "music_assistant"
    assert guest.state.calls[0].data["media_id"] == "library://track/1"
    assert (await invoke(hass, guest, tool, args)).error
    assert len(guest.state.calls) == 1


async def test_music_revocation_before_final_admission_executes_nothing(hass, guest, monkeypatch):
    policy = AsyncMock(side_effect=[True, False])
    monkeypatch.setattr(guest_control, "async_check_guest_action", policy)
    result = await invoke(
        hass, guest, GuestMusicControlTool(guest.auth, ("media_player.guest",)),
        {"action": "resume", "speaker": "media_player.guest"},
    )
    assert result.error
    assert guest.state.calls == []


async def test_factory_projects_only_policy_rows_and_no_arbitrary_tools(hass, guest):
    result = await async_guest_tools(
        hass, guest.auth, ("switch.guest", "media_player.guest", "sensor.private"),
        player_ids=("media_player.guest",),
    )
    assert "sensor.private" not in result["prompt"]
    assert {tool.name for tool in result["tools"]} == {
        "codex_assist__guest_on_off", "codex_assist__guest_music",
    }
    guest.state.current = False
    assert await async_guest_tools(hass, guest.auth, ("switch.guest",)) is None
