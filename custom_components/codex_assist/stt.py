"""Separate, explicitly enabled learning and clean-message STT platforms."""

from .entry_modules import EntryModule, entry_module


async def async_setup_entry(hass, entry, async_add_entities):
    if entry_module(entry) is EntryModule.VOICE_MATCH:
        from .learning.stt import async_setup_entry as setup_learning_stt

        await setup_learning_stt(hass, entry, async_add_entities)
    else:
        from .voice_match import CONF_CLEAN_TRANSCRIPT, CONF_VOICE_MATCH_HOST

        if entry.options.get(CONF_CLEAN_TRANSCRIPT):
            from .voice_match_stt import VoiceMatchSttAdapter

            backend = None
            if CONF_VOICE_MATCH_HOST in entry.options:
                from .voice_match_backend import async_backend

                try:
                    backend = await async_backend(hass, entry.options)
                except ValueError:
                    # Malformed saved options must not take Codex/AI Task offline.
                    pass
            async_add_entities([VoiceMatchSttAdapter(entry, None, managed=True, backend=backend)])
