"""Development-only paired STT adapter, not registered by integration setup.

The provider interface is native HA; the object-bound handoff is experimental.
Production setup/options must remain unchanged until pipeline contracts pass.
"""

from homeassistant.components import stt

from .speaker_packet import PacketError
from .voice_match import CONF_VOICE_MATCH_KEY, runtime_for_entry


class VoiceMatchSttAdapter(stt.SpeechToTextEntity):
    """Wrap a personalised Wyoming STT entity without publishing its wire header."""

    _attr_has_entity_name = True
    _attr_name = "Voice Match clean transcript (prototype)"

    def __init__(self, entry, source):
        self._entry = entry
        self._source = source
        self._attr_unique_id = f"{entry.entry_id}_voice_match_stt_prototype"

    @property
    def supported_languages(self):
        return self._source.supported_languages

    @property
    def supported_formats(self):
        return self._source.supported_formats

    @property
    def supported_codecs(self):
        return self._source.supported_codecs

    @property
    def supported_bit_rates(self):
        return self._source.supported_bit_rates

    @property
    def supported_sample_rates(self):
        return self._source.supported_sample_rates

    @property
    def supported_channels(self):
        return self._source.supported_channels

    @property
    def audio_processing(self):
        return self._source.audio_processing

    async def async_process_audio_stream(self, metadata, stream):
        key = self._entry.options.get(CONF_VOICE_MATCH_KEY, "")
        if not key:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        result = await self._source.async_process_audio_stream(metadata, stream)
        if result.result != stt.SpeechResultState.SUCCESS or not result.text:
            return result
        # A key change during recording must not produce a new-key/old-key mix.
        if self._entry.options.get(CONF_VOICE_MATCH_KEY, "") != key:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        try:
            text = runtime_for_entry(self._entry).handoffs.issue(key, result.text)
        except PacketError:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        return stt.SpeechResult(text, stt.SpeechResultState.SUCCESS)
