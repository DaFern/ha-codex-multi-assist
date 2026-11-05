from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .entry_modules import ModuleConfigEntry

from .entry_modules import EntryModule, entry_module

DOMAIN = "codex_assist"


async def async_setup_entry(hass: HomeAssistant, entry: ModuleConfigEntry) -> bool:
    """Dispatch by module before importing any provider-specific lifecycle."""
    from homeassistant.exceptions import ConfigEntryError

    try:
        module = entry_module(entry)
    except (ValueError, TypeError):
        raise ConfigEntryError("Unsupported integration module") from None
    if module is EntryModule.CODEX:
        from .codex_entry import async_setup_codex

        return await async_setup_codex(hass, entry)
    # Phase 1 reserves the boundary, not a working learning implementation.
    raise ConfigEntryError("Voice Match learning is not available in this development stage")


async def async_update_listener(hass: HomeAssistant, entry: ModuleConfigEntry) -> None:
    """Reload only the entry whose settings changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ModuleConfigEntry) -> bool:
    """A module cannot unload another module's platforms."""
    if entry.runtime_data.module is EntryModule.CODEX:
        from .codex_entry import async_unload_codex

        return await async_unload_codex(hass, entry)
    return False
