"""STT is forwarded only by the explicitly enabled learning entry."""

from .entry_modules import EntryModule, entry_module


async def async_setup_entry(hass, entry, async_add_entities):
    if entry_module(entry) is EntryModule.VOICE_MATCH:
        from .learning.stt import async_setup_entry as setup_learning_stt

        await setup_learning_stt(hass, entry, async_add_entities)
