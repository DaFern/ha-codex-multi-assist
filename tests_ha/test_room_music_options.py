"""Real native options flow for administrator-owned routing, not access grants."""

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist.room_music import CONF_ROOM_MUSIC_DEFAULTS
from custom_components.codex_assist.satellite_runtime import satellite_tools_supported


async def test_room_defaults_menu_is_capability_gated(hass):
    entry = MockConfigEntry(domain="codex_assist", data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert ("room_music_defaults" in result["menu_options"]) is satellite_tools_supported()


@pytest.fixture
def room_settings(hass):
    if not satellite_tools_supported():
        pytest.skip("Room music tools require modern HA")
    area = ar.async_get(hass).async_create("Test room")
    other = ar.async_get(hass).async_create("Other room")
    music_entry = MockConfigEntry(domain="music_assistant")
    music_entry.add_to_hass(hass)
    player = er.async_get(hass).async_get_or_create(
        "media_player", "music_assistant", "room-default", config_entry=music_entry,
    )
    entry = MockConfigEntry(
        domain="codex_assist", data={}, options={
            "prompt": "Keep unrelated options", "music_player_ids": [],
            CONF_ROOM_MUSIC_DEFAULTS: {other.id: player.entity_id},
        },
    )
    entry.add_to_hass(hass)
    return entry, area, other, player


async def choose_room(hass, entry, area_id):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "room_music_defaults"},
    )
    assert result["step_id"] == "room_music_defaults"
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"area_id": area_id},
    )


async def test_room_default_save_edit_and_remove_preserve_other_options(hass, room_settings):
    entry, area, other, player = room_settings
    result = await choose_room(hass, entry, area.id)
    assert result["step_id"] == "room_music_default"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"player_id": player.entity_id},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {
        "prompt": "Keep unrelated options", "music_player_ids": [],
        CONF_ROOM_MUSIC_DEFAULTS: {other.id: player.entity_id, area.id: player.entity_id},
    }
    result = await choose_room(hass, entry, area.id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"remove_default": True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ROOM_MUSIC_DEFAULTS] == {other.id: player.entity_id}
    result = await choose_room(hass, entry, other.id)
    await hass.config_entries.options.async_configure(result["flow_id"], {"remove_default": True})
    assert CONF_ROOM_MUSIC_DEFAULTS not in entry.options
    assert entry.options["music_player_ids"] == []  # Selecting defaults grants no access.


@pytest.mark.parametrize("invalid", ["missing", "wrong_platform", "disabled", "deleted_area"])
async def test_room_default_revalidates_registry_without_losing_settings(
    hass, room_settings, invalid,
):
    entry, area, other, player = room_settings
    result = await choose_room(hass, entry, area.id)
    if invalid == "missing":
        selected = "media_player.missing"
    elif invalid == "wrong_platform":
        selected = er.async_get(hass).async_get_or_create(
            "media_player", "test", "not-music",
        ).entity_id
    elif invalid == "disabled":
        er.async_get(hass).async_update_entity(
            player.entity_id, disabled_by=er.RegistryEntryDisabler.USER,
        )
        selected = player.entity_id
    else:
        ar.async_get(hass).async_delete(area.id)
        selected = player.entity_id
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"player_id": selected},
    )
    assert result["errors"] == {"base": "invalid_room_music_player"}
    assert entry.options[CONF_ROOM_MUSIC_DEFAULTS] == {other.id: player.entity_id}


async def test_room_default_conflict_is_refused_but_other_room_updates_are_preserved(
    hass, room_settings,
):
    entry, area, other, player = room_settings
    result = await choose_room(hass, entry, area.id)
    hass.config_entries.async_update_entry(entry, options={
        **entry.options, "prompt": "New unrelated setting",
        CONF_ROOM_MUSIC_DEFAULTS: {},
    })
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"player_id": player.entity_id},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ROOM_MUSIC_DEFAULTS] == {area.id: player.entity_id}
    assert entry.options["prompt"] == "New unrelated setting"
    result = await choose_room(hass, entry, other.id)
    hass.config_entries.async_update_entry(entry, options={
        **entry.options,
        CONF_ROOM_MUSIC_DEFAULTS: {area.id: player.entity_id, other.id: player.entity_id},
    })
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"remove_default": True},
    )
    assert result["errors"] == {"base": "room_music_default_changed"}
    assert entry.options[CONF_ROOM_MUSIC_DEFAULTS][other.id] == player.entity_id


async def test_deleted_room_mapping_can_be_removed(hass, room_settings):
    entry, _area, other, player = room_settings
    ar.async_get(hass).async_delete(other.id)
    result = await choose_room(hass, entry, other.id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"remove_default": True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_ROOM_MUSIC_DEFAULTS not in entry.options


async def test_entry_owned_dispatcher_reads_room_default_setting(hass, room_settings):
    from custom_components.codex_assist.rbac_satellite import ProtectedSatelliteDispatcher

    entry, _area, other, player = room_settings
    dispatcher = ProtectedSatelliteDispatcher.for_entry(
        hass, entry, candidate_entity_ids=(player.entity_id,),
    )
    assert dispatcher._room_defaults_provider() == {other.id: player.entity_id}
    dispatcher.close()
