"""Codex-only platform lifecycle; does not connect to the Voice Match add-on."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers.event import async_track_time_interval

from .codex_models import MODEL_CACHE_SECONDS
from .entry_modules import EntryModule, ModuleRuntime
from .model_discovery import async_entry_model_catalog
from .satellite_runtime import satellite_tools_supported
from .voice_match import (
    CONF_CLEAN_TRANSCRIPT,
    CONF_VOICE_MATCH_KEY,
    runtime_for_entry,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .entry_modules import ModuleConfigEntry


async def async_setup_codex(hass: HomeAssistant, entry: ModuleConfigEntry) -> bool:
    """Start only Codex platforms and model refresh, without touching OAuth locks."""
    from . import async_update_listener

    platforms = (Platform.CONVERSATION, Platform.AI_TASK)
    if entry.options.get(CONF_CLEAN_TRANSCRIPT):
        from homeassistant.exceptions import ConfigEntryError

        from .entry_modules import learning_supported
        from .speaker_packet import valid_key

        if not learning_supported() or not valid_key(entry.options.get(CONF_VOICE_MATCH_KEY, "")):
            raise ConfigEntryError(
                "Clean voice messages require HA 2026.10+ and Voice Match pairing"
            )
        platforms += (Platform.STT,)
    entry.runtime_data = ModuleRuntime(EntryModule.CODEX, platforms)
    await hass.config_entries.async_forward_entry_setups(entry, entry.runtime_data.platforms)
    # API registration alone also exists on older HA without modern tool types.
    if satellite_tools_supported():
        from .music_api import async_register_music_api

        entry.async_on_unload(async_register_music_api(hass))
        if entry.options.get("protected_satellite_ids"):
            from .kiosk_adapter import setup_entry_adapter

            setup_entry_adapter(hass, entry)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    async def refresh_models(_now) -> None:
        await async_entry_model_catalog(hass, entry)

    entry.async_on_unload(
        async_track_time_interval(hass, refresh_models, timedelta(seconds=MODEL_CACHE_SECONDS))
    )
    return True


async def async_unload_codex(hass: HomeAssistant, entry: ModuleConfigEntry) -> bool:
    """Unload only the platforms recorded for this Codex entry."""
    if entry.entry_id in hass.data.get("codex_assist_protected_satellites", {}):
        from .kiosk_adapter import async_stop_entry_adapter

        await async_stop_entry_adapter(hass, entry)
    await runtime_for_entry(entry).async_stop_clean_requests()
    return await hass.config_entries.async_unload_platforms(entry, entry.runtime_data.platforms)
