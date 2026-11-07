"""One Voice Match STT engine; the object-bound handoff remains experimental."""

import asyncio
from datetime import timedelta

from homeassistant.components import stt
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

from .speaker_packet import PacketError, valid_key
from .voice_match import (
    CONF_CLEAN_TRANSCRIPT,
    CONF_PERSONAL_STT_SOURCE,
    CONF_VOICE_MATCH_HOST,
    CONF_VOICE_MATCH_KEY,
    runtime_for_entry,
)


def resolve_personal_source(hass, entity_id):
    """Read registry/runtime metadata, never trust an entity's editable label.

    Service discovery is a compatibility check, not speaker authentication: every
    result still needs a valid, utterance-bound packet from the paired sender.
    """
    if (not isinstance(entity_id, str) or not entity_id.startswith("stt.")
            or "stt" not in hass.config.components):
        return None
    registered = er.async_get(hass).async_get(entity_id)
    if (registered is None or registered.platform != "wyoming"
            or registered.disabled_by is not None):
        return None
    entry = hass.config_entries.async_get_entry(registered.config_entry_id)
    if entry is None or entry.domain != "wyoming" or entry.disabled_by is not None:
        return None
    source = stt.async_get_speech_to_text_entity(hass, entity_id)
    if (source is None or not source.available or source.platform is None
            or source.platform.platform_name != "wyoming"):
        return None
    service = getattr(source, "service", None)
    asr = getattr(getattr(service, "info", None), "asr", None)
    if (not isinstance(asr, list) or not asr
            or getattr(asr[0], "name", None) != "voice-match-personal"):
        return None
    return source


class VoiceMatchSttAdapter(stt.SpeechToTextEntity):
    """Read personalised Wyoming STT without publishing its wire header."""

    _attr_has_entity_name = True
    _attr_name = "Voice Match"

    def __init__(self, entry, source, *, managed=False, backend=None):
        self._entry = entry
        self._prototype_source = source
        self._managed = managed
        self._backend = backend
        self._runtime = runtime_for_entry(entry)
        self._generation = self._runtime.clean_generation
        suffix = "voice_match_clean_stt" if managed else "voice_match_stt_prototype"
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"

    @property
    def _source(self):
        if not self._managed:
            return self._prototype_source
        if CONF_VOICE_MATCH_HOST in self._entry.options:
            from .voice_match_backend import endpoint

            try:
                if (self._backend is not None and self._backend.available
                        and self._backend.endpoint == endpoint(self._entry.options)):
                    return self._backend
            except ValueError:
                pass
            return None
        return resolve_personal_source(self.hass, self._entry.options.get(CONF_PERSONAL_STT_SOURCE))

    def _enabled(self):
        return (self._generation == self._runtime.clean_generation
                and self._entry.options.get(CONF_CLEAN_TRANSCRIPT) is True
                and valid_key(self._entry.options.get(CONF_VOICE_MATCH_KEY, "")))

    @property
    def available(self):
        return (not self._managed or self._enabled()) and self._source is not None

    @property
    def supported_languages(self):
        return source.supported_languages if (source := self._source) is not None else []

    @property
    def supported_formats(self):
        return source.supported_formats if (source := self._source) is not None else []

    @property
    def supported_codecs(self):
        return source.supported_codecs if (source := self._source) is not None else []

    @property
    def supported_bit_rates(self):
        return source.supported_bit_rates if (source := self._source) is not None else []

    @property
    def supported_sample_rates(self):
        return source.supported_sample_rates if (source := self._source) is not None else []

    @property
    def supported_channels(self):
        return source.supported_channels if (source := self._source) is not None else []

    @property
    def audio_processing(self):
        if (source := self._source) is not None:
            return source.audio_processing
        return stt.SpeechAudioProcessing(True, False, False)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self._backend is not None:
            self.async_on_remove(async_track_time_interval(
                self.hass, self._refresh_backend, timedelta(seconds=30),
            ))
        source_id = self._entry.options.get(CONF_PERSONAL_STT_SOURCE)
        if self._managed and isinstance(source_id, str):
            self.async_on_remove(async_track_state_change_event(
                self.hass, [source_id],
                self._source_state_changed,
            ))

    @callback
    def _source_state_changed(self, _event):
        self.async_write_ha_state()

    async def _refresh_backend(self, _now):
        await self._backend.async_refresh()
        if self._enabled():
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        if self._managed:
            await self._runtime.async_stop_clean_requests()

    async def async_process_audio_stream(self, metadata, stream):
        key = self._entry.options.get(CONF_VOICE_MATCH_KEY, "")
        source_id = self._entry.options.get(CONF_PERSONAL_STT_SOURCE)
        if not key or (self._managed and not self._enabled()):
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        source = self._source
        if source is None:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        if self._managed:
            try:
                self._runtime.track_clean_task(asyncio.current_task())
            except PacketError:
                return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        try:
            result = await source.async_process_audio_stream(metadata, stream)
        except asyncio.CancelledError:
            raise
        except Exception:
            # No raw transcript/exception fallback and no second audio submission.
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        finally:
            if self._backend is not None and self._enabled():
                self.async_write_ha_state()
        if self._managed and (not self._enabled() or self._source is not source
                              or self._entry.options.get(CONF_PERSONAL_STT_SOURCE) != source_id):
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        if result.result != stt.SpeechResultState.SUCCESS or not result.text:
            # An error response may still contain a private header. Never publish it.
            return stt.SpeechResult(None, result.result)
        # A key change during recording must not produce a new-key/old-key mix.
        if self._entry.options.get(CONF_VOICE_MATCH_KEY, "") != key:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        try:
            text = runtime_for_entry(self._entry).handoffs.issue(key, result.text)
        except PacketError:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        return stt.SpeechResult(text, stt.SpeechResultState.SUCCESS)
