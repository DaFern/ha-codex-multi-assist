"""Separate, explicitly enabled learning and clean-message STT platforms."""

from .entry_modules import EntryModule, entry_module


async def async_setup_entry(hass, entry, async_add_entities):
    if entry_module(entry) is EntryModule.VOICE_MATCH:
        from .learning.stt import async_setup_entry as setup_learning_stt

        await setup_learning_stt(hass, entry, async_add_entities)
    else:
        from .voice_match import CONF_CLEAN_TRANSCRIPT

        if entry.options.get(CONF_CLEAN_TRANSCRIPT):
            from .voice_match_stt import VoiceMatchSttAdapter

            async_add_entities([VoiceMatchSttAdapter(entry, None, managed=True)])
