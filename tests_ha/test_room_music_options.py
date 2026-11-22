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


async def finish_rooms(hass, result):
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "room_music_continue"
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "room_music_save"},
    )


async def another_room(hass, result, area_id):
    assert result["step_id"] == "room_music_continue"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "room_music_defaults"},
    )
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
    assert entry.options[CONF_ROOM_MUSIC_DEFAULTS] == {other.id: player.entity_id}
    result = await finish_rooms(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {
        "prompt": "Keep unrelated options", "music_player_ids": [],
        CONF_ROOM_MUSIC_DEFAULTS: {other.id: player.entity_id, area.id: player.entity_id},
    }
    result = await choose_room(hass, entry, area.id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"remove_default": True},
    )
    result = await finish_rooms(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ROOM_MUSIC_DEFAULTS] == {other.id: player.entity_id}
    result = await choose_room(hass, entry, other.id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"remove_default": True},
    )
    await finish_rooms(hass, result)
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
    result = await finish_rooms(hass, result)
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
    result = await finish_rooms(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_ROOM_MUSIC_DEFAULTS not in entry.options


async def test_multiple_rooms_can_be_added_edited_and_removed_without_leaving_flow(
    hass, room_settings,
):
    entry, area, other, player = room_settings
    original = dict(entry.options)
    third = ar.async_get(hass).async_create("Third room")
    second_player = er.async_get(hass).async_get_or_create(
        "media_player", "music_assistant", "second-room-default",
        config_entry=hass.config_entries.async_get_entry(player.config_entry_id),
    )
    result = await choose_room(hass, entry, area.id)
    flow_id = result["flow_id"]
    result = await hass.config_entries.options.async_configure(
        flow_id, {"player_id": player.entity_id},
    )
    result = await another_room(hass, result, third.id)
    result = await hass.config_entries.options.async_configure(
        flow_id, {"player_id": player.entity_id},
    )
    result = await another_room(hass, result, area.id)
    suggested = next(key for key in result["data_schema"].schema if key == "player_id")
    assert suggested.description["suggested_value"] == player.entity_id
    result = await hass.config_entries.options.async_configure(
        flow_id, {"player_id": second_player.entity_id},
    )
    result = await another_room(hass, result, other.id)
    result = await hass.config_entries.options.async_configure(flow_id, {"remove_default": True})
    assert result["flow_id"] == flow_id
    assert dict(entry.options) == original  # No save/reload while adding rooms.
    result = await finish_rooms(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {
        **original,
        CONF_ROOM_MUSIC_DEFAULTS: {
            area.id: second_player.entity_id, third.id: player.entity_id,
        },
    }


async def test_cancelling_discards_all_staged_room_changes(hass, room_settings):
    entry, area, _other, player = room_settings
    original = dict(entry.options)
    result = await choose_room(hass, entry, area.id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"player_id": player.entity_id},
    )
    hass.config_entries.options.async_abort(result["flow_id"])
    assert dict(entry.options) == original


async def test_finish_rechecks_conflicts_in_previously_staged_rooms(hass, room_settings):
    entry, area, other, player = room_settings
    result = await choose_room(hass, entry, area.id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"player_id": player.entity_id},
    )
    result = await another_room(hass, result, other.id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"remove_default": True},
    )
    hass.config_entries.async_update_entry(entry, options={
        **entry.options,
        CONF_ROOM_MUSIC_DEFAULTS: {area.id: "media_player.changed", other.id: player.entity_id},
    })
    original = dict(entry.options)
    result = await finish_rooms(hass, result)
    assert result["errors"] == {"base": "room_music_default_changed"}
    assert dict(entry.options) == original  # No partial removal of the other room.


@pytest.mark.parametrize("problem", ["player_removed", "player_disabled", "area_removed"])
async def test_finish_revalidates_staged_rooms_before_atomic_save(hass, room_settings, problem):
    entry, area, _other, player = room_settings
    original = dict(entry.options)
    result = await choose_room(hass, entry, area.id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"player_id": player.entity_id},
    )
    if problem == "player_removed":
        er.async_get(hass).async_remove(player.entity_id)
    elif problem == "player_disabled":
        er.async_get(hass).async_update_entity(
            player.entity_id, disabled_by=er.RegistryEntryDisabler.USER,
        )
    else:
        ar.async_get(hass).async_delete(area.id)
    result = await finish_rooms(hass, result)
    assert result["errors"] == {"base": "invalid_room_music_player"}
    assert dict(entry.options) == original


async def test_finish_preserves_settings_changed_after_staging(hass, room_settings):
    entry, area, other, player = room_settings
    result = await choose_room(hass, entry, area.id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"player_id": player.entity_id},
    )
    hass.config_entries.async_update_entry(entry, options={
        **entry.options, "prompt": "Updated elsewhere", CONF_ROOM_MUSIC_DEFAULTS: {},
    })
    result = await finish_rooms(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ROOM_MUSIC_DEFAULTS] == {area.id: player.entity_id}
    assert entry.options["prompt"] == "Updated elsewhere"
    assert other.id not in entry.options[CONF_ROOM_MUSIC_DEFAULTS]


async def test_draft_removal_frees_capacity_for_another_room(hass, room_settings):
    entry, area, _other, player = room_settings
    defaults = {f"old_room_{index}": player.entity_id for index in range(64)}
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_ROOM_MUSIC_DEFAULTS: defaults},
    )
    result = await choose_room(hass, entry, area.id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"player_id": player.entity_id},
    )
    assert result["errors"] == {"base": "invalid_room_music_player"}
    hass.config_entries.options.async_abort(result["flow_id"])
    result = await choose_room(hass, entry, "old_room_0")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"remove_default": True},
    )
    result = await another_room(hass, result, area.id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"player_id": player.entity_id},
    )
    result = await finish_rooms(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(entry.options[CONF_ROOM_MUSIC_DEFAULTS]) == 64
    assert "old_room_0" not in entry.options[CONF_ROOM_MUSIC_DEFAULTS]
    assert entry.options[CONF_ROOM_MUSIC_DEFAULTS][area.id] == player.entity_id


async def test_finish_refuses_combined_defaults_over_capacity(hass, room_settings):
    entry, area, _other, player = room_settings
    defaults = {f"old_room_{index}": player.entity_id for index in range(63)}
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_ROOM_MUSIC_DEFAULTS: defaults},
    )
    result = await choose_room(hass, entry, area.id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"player_id": player.entity_id},
    )
    hass.config_entries.async_update_entry(entry, options={
        **entry.options,
        CONF_ROOM_MUSIC_DEFAULTS: {**defaults, "concurrent_room": player.entity_id},
    })
    original = dict(entry.options)
    result = await finish_rooms(hass, result)
    assert result["errors"] == {"base": "invalid_room_music_player"}
    assert dict(entry.options) == original


async def test_entry_owned_dispatcher_reads_room_default_setting(hass, room_settings):
    from custom_components.codex_assist.rbac_satellite import ProtectedSatelliteDispatcher

    entry, _area, other, player = room_settings
    dispatcher = ProtectedSatelliteDispatcher.for_entry(
        hass, entry, candidate_entity_ids=(player.entity_id,),
    )
    assert dispatcher._room_defaults_provider() == {other.id: player.entity_id}
    dispatcher.close()
