"""Native options editor for per-entry room music defaults."""

import voluptuous as vol
from homeassistant.helpers import selector

from .room_music import CONF_ROOM_MUSIC_DEFAULTS, MAX_ROOM_MUSIC_DEFAULTS, room_music_defaults
from .satellite_runtime import satellite_tools_supported


class RoomMusicOptionsMixin:
    """Stage multiple room edits, then save once without replacing unrelated options."""

    async def async_step_room_music_defaults(self, user_input=None):
        if not satellite_tools_supported():
            return self.async_abort(reason="satellite_requires_current_ha")
        from homeassistant.helpers import area_registry as ar

        defaults = room_music_defaults(self.config_entry.options.get(CONF_ROOM_MUSIC_DEFAULTS, {}))
        if defaults is None:
            return self.async_abort(reason="invalid_room_music_defaults")
        if not hasattr(self, "_room_music_changes"):
            self._room_music_changes = {}
            self._room_music_expected = {}
        current_defaults = dict(defaults)
        for room, player in self._room_music_changes.items():
            if player is None:
                defaults.pop(room, None)
            else:
                defaults[room] = player
        areas = {area.id: area.name for area in ar.async_get(self.hass).async_list_areas()}
        choices = [
            selector.SelectOptionDict(value=area, label=areas.get(area, f"Removed room ({area})"))
            for area in sorted(areas.keys() | defaults.keys(), key=lambda key: areas.get(key, key))
        ]
        if not choices:
            return self.async_abort(reason="no_music_rooms")
        if user_input is not None:
            area = user_input.get("area_id")
            if type(area) is str and (area in areas or area in defaults):
                self._room_music_area_id = area
                self._room_music_expected.setdefault(area, current_defaults.get(area))
                return await self.async_step_room_music_default()
        return self.async_show_form(
            step_id="room_music_defaults",
            data_schema=vol.Schema({
                vol.Required("area_id"): selector.SelectSelector(selector.SelectSelectorConfig(
                    options=choices, mode=selector.SelectSelectorMode.DROPDOWN,
                )),
            }),
        )

    async def async_step_room_music_default(self, user_input=None):
        if not satellite_tools_supported():
            return self.async_abort(reason="satellite_requires_current_ha")
        if not getattr(self, "_room_music_area_id", None):
            return await self.async_step_room_music_defaults()
        from homeassistant.helpers import area_registry as ar
        from homeassistant.helpers import entity_registry as er

        area_id = self._room_music_area_id
        area = ar.async_get(self.hass).async_get_area(area_id)
        defaults = room_music_defaults(self.config_entry.options.get(CONF_ROOM_MUSIC_DEFAULTS, {}))
        errors = {}
        if defaults is None:
            return self.async_abort(reason="invalid_room_music_defaults")
        draft = dict(defaults)
        for room, player in self._room_music_changes.items():
            if player is None:
                draft.pop(room, None)
            else:
                draft[room] = player
        if user_input is not None:
            player = user_input.get("player_id")
            remove = user_input.get("remove_default", False) is True
            entry = er.async_get(self.hass).async_get(player) if type(player) is str else None
            if defaults.get(area_id) != self._room_music_expected[area_id]:
                errors["base"] = "room_music_default_changed"
            elif not remove and (
                area is None or entry is None or entry.domain != "media_player"
                or entry.platform != "music_assistant" or entry.disabled_by is not None
                or (area_id not in draft and len(draft) >= MAX_ROOM_MUSIC_DEFAULTS)
            ):
                errors["base"] = "invalid_room_music_player"
            else:
                self._room_music_changes[area_id] = None if remove else player
                return await self.async_step_room_music_continue()
        suggested = self._room_music_changes.get(area_id, defaults.get(area_id))
        return self.async_show_form(
            step_id="room_music_default",
            data_schema=vol.Schema({
                vol.Optional("player_id", description=(
                    {"suggested_value": suggested} if suggested else {}
                )): selector.EntitySelector(selector.EntitySelectorConfig(
                    domain="media_player", integration="music_assistant",
                )),
                vol.Optional("remove_default", default=False): bool,
            }),
            errors=errors,
            description_placeholders={"room": area.name if area else "Removed room"},
        )

    async def async_step_room_music_continue(self, user_input=None):
        """Keep the options dialog open after each staged room change."""
        if not satellite_tools_supported():
            return self.async_abort(reason="satellite_requires_current_ha")
        if not getattr(self, "_room_music_changes", None):
            return await self.async_step_room_music_defaults()
        return self.async_show_menu(
            step_id="room_music_continue",
            menu_options=["room_music_defaults", "room_music_save"],
        )

    async def async_step_room_music_save(self, user_input=None):
        """Recheck every staged edit against live settings and registries before saving."""
        if not satellite_tools_supported():
            return self.async_abort(reason="satellite_requires_current_ha")
        if not getattr(self, "_room_music_changes", None):
            return await self.async_step_room_music_defaults()
        from homeassistant.helpers import area_registry as ar
        from homeassistant.helpers import entity_registry as er

        defaults = room_music_defaults(self.config_entry.options.get(CONF_ROOM_MUSIC_DEFAULTS, {}))
        if defaults is None:
            return self.async_abort(reason="invalid_room_music_defaults")
        errors = {}
        for area_id, player in self._room_music_changes.items():
            if defaults.get(area_id) != self._room_music_expected[area_id]:
                errors["base"] = "room_music_default_changed"
                break
            if player is None:
                defaults.pop(area_id, None)
                continue
            entry = er.async_get(self.hass).async_get(player)
            if (
                ar.async_get(self.hass).async_get_area(area_id) is None
                or entry is None or entry.domain != "media_player"
                or entry.platform != "music_assistant" or entry.disabled_by is not None
            ):
                errors["base"] = "invalid_room_music_player"
                break
            defaults[area_id] = player
        if len(defaults) > MAX_ROOM_MUSIC_DEFAULTS:
            errors["base"] = "invalid_room_music_player"
        if errors:
            return self.async_show_form(
                step_id="room_music_save", data_schema=vol.Schema({}), errors=errors,
            )
        options = dict(self.config_entry.options)
        if defaults:
            options[CONF_ROOM_MUSIC_DEFAULTS] = defaults
        else:
            options.pop(CONF_ROOM_MUSIC_DEFAULTS, None)
        return self.async_create_entry(title="", data=options)
