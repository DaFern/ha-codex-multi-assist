"""Codex-only platform lifecycle; does not connect to the Voice Match add-on."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers.event import async_track_time_interval

from .codex_models import MODEL_CACHE_SECONDS
from .entry_modules import EntryModule, ModuleRuntime
from .model_discovery import async_entry_model_catalog

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .entry_modules import ModuleConfigEntry


async def async_setup_codex(hass: HomeAssistant, entry: ModuleConfigEntry) -> bool:
    """Start only Codex platforms and model refresh, without touching OAuth locks."""
    from . import async_update_listener

    entry.runtime_data = ModuleRuntime(
        EntryModule.CODEX, (Platform.CONVERSATION, Platform.AI_TASK)
    )
    await hass.config_entries.async_forward_entry_setups(entry, entry.runtime_data.platforms)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    async def refresh_models(_now) -> None:
        await async_entry_model_catalog(hass, entry)

    entry.async_on_unload(
        async_track_time_interval(hass, refresh_models, timedelta(seconds=MODEL_CACHE_SECONDS))
    )
    return True


async def async_unload_codex(hass: HomeAssistant, entry: ModuleConfigEntry) -> bool:
    """Unload only the platforms recorded for this Codex entry."""
    return await hass.config_entries.async_unload_platforms(entry, entry.runtime_data.platforms)
