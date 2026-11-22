"""Administrator-owned room routing preferences, never permission grants."""

from collections.abc import Mapping

CONF_ROOM_MUSIC_DEFAULTS = "room_music_defaults"
MAX_ROOM_MUSIC_DEFAULTS = 64


def room_music_defaults(value):
    """Copy bounded routing data; malformed mappings must not silently fall back."""
    if value is None:
        return {}
    if (not isinstance(value, Mapping) or len(value) > MAX_ROOM_MUSIC_DEFAULTS
            or any(type(area) is not str or not 0 < len(area) <= 128
                   or type(player) is not str or not player.startswith("media_player.")
                   or not 0 < len(player) <= 255 for area, player in value.items())):
        return None
    return dict(value)


def player_area_id(hass, entry):
    """Honor an entity's explicit area before its device's inherited area."""
    from homeassistant.helpers import device_registry as dr

    if entry is None:
        return None
    if entry.area_id:
        return entry.area_id
    if entry.device_id:
        device = dr.async_get(hass).async_get(entry.device_id)
        if device:
            return dr.async_get_effective_area_id(hass, device)
    return None
