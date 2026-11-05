from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .entry_modules import ModuleConfigEntry

from .entry_modules import EntryModule, entry_module, learning_supported

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
    if not learning_supported():
        raise ConfigEntryError("Voice Match learning requires Home Assistant 2026.10 or later")
    from .learning.lifecycle import async_setup_learning

    return await async_setup_learning(hass, entry)


async def async_update_listener(hass: HomeAssistant, entry: ModuleConfigEntry) -> None:
    """Reload only the entry whose settings changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ModuleConfigEntry) -> bool:
    """A module cannot unload another module's platforms."""
    if entry.runtime_data.module is EntryModule.CODEX:
        from .codex_entry import async_unload_codex

        return await async_unload_codex(hass, entry)
    if entry.runtime_data.module is EntryModule.VOICE_MATCH:
        from .learning.lifecycle import async_unload_learning

        return await async_unload_learning(hass, entry)
    return False
