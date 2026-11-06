"""Opt-in learning STT. Buffer briefly; never train at the unauthorised STT stage."""

import asyncio
from dataclasses import replace

from homeassistant.components import stt
from homeassistant.components.websocket_api.connection import (
    ActiveConnection,
    current_connection,
)
from homeassistant.helpers import chat_session

from .phone_diagnostics import record
from .phone_flow import MARKER, control_category


def control_source(hass, entity_id):
    # This optional module no longer has a global hard STT dependency. A source
    # that has not loaded yet must retry this entry, not crash or start Codex.
    if "stt" not in hass.config.components:
        raise ValueError("Select an existing ordinary Wyoming Whisper STT engine")
    source = stt.async_get_speech_to_text_entity(hass, entity_id)
    if (
        source is None
        or isinstance(source, PhoneLearningStt)
        or source.platform is None
        or source.platform.platform_name != "wyoming"
        or not any(language in source.supported_languages for language in ("en", "en-GB", "en-US"))
    ):
        raise ValueError("Select an existing ordinary Wyoming Whisper STT engine")
    return source


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = entry.runtime_data.phone
    if runtime is not None:
        async_add_entities([PhoneLearningStt(entry, runtime)])


class PhoneLearningStt(stt.SpeechToTextEntity):
    _attr_has_entity_name = True
    _attr_name = "Voice Learning"

    def __init__(self, entry, runtime):
        self._attr_unique_id = entry.entry_id + "_phone_learning_stt"
        self.runtime = runtime

    @property
    def supported_languages(self):
        return ["en"]

    @property
    def supported_formats(self):
        return [stt.AudioFormats.WAV]

    @property
    def supported_codecs(self):
        return [stt.AudioCodecs.PCM]

    @property
    def supported_bit_rates(self):
        return [stt.AudioBitRates.BITRATE_16]

    @property
    def supported_sample_rates(self):
        return [stt.AudioSampleRates.SAMPLERATE_16000]

    @property
    def supported_channels(self):
        return [stt.AudioChannels.CHANNEL_MONO]

    @property
    def audio_processing(self):
        return control_source(self.hass, self.runtime.source_id).audio_processing

    async def async_process_audio_stream(self, metadata, stream):
        owner = None
        audio = bytearray()
        stage = "binding"
        try:
            connection = current_connection.get()
            session = chat_session.current_session.get()
            if (
                not isinstance(connection, ActiveConnection)
                or connection.hass is not self.hass
                or session is None
            ):
                raise ValueError("An authenticated phone pipeline is required")
            stage = "account_or_metadata"
            user = await self.hass.auth.async_get_user(connection.user.id)
            if (
                user is None
                or not user.is_active
                or user.system_generated
                or not self.check_metadata(metadata)
            ):
                raise ValueError("Phone caller unavailable")
            stage = "reserve"
            login_id = self.runtime.authorize(connection, user.id)
            self.runtime.watch(connection)
            owner = self.runtime.frames.reserve(connection, user.id, session, login_id=login_id)
            stage = "prepare"
            permit = await self.runtime.controller.prepare(
                connection, user.id, session.conversation_id, login_id
            )
            self.runtime.frames.set_permit(owner, permit)
            stage = "source"
            source = control_source(self.hass, self.runtime.source_id)
            language = next(
                language
                for language in ("en", "en-GB", "en-US")
                if language in source.supported_languages
            )
            source_metadata = replace(metadata, language=language)
            stage = "source_metadata"
            if not source.check_metadata(source_metadata):
                raise ValueError("Whisper does not support the recording format")
            async with asyncio.timeout(45):
                iterator = aiter(stream)
                capture_failed = False

                async def capture():
                    nonlocal stage, capture_failed
                    try:
                        async for chunk in iterator:
                            if not isinstance(chunk, bytes) or len(audio) + len(chunk) > 320000:
                                stage, capture_failed = "audio_limit", True
                                raise ValueError("Recording exceeds ten seconds")
                            audio.extend(chunk)
                            # Preserve source streaming/endpointer behaviour. Waiting
                            # for client EOF before invoking STT can deadlock a client
                            # that waits for STT_END before it stops sending audio.
                            yield chunk
                    except Exception:
                        # Providers must not accept an interrupted clip.
                        if not capture_failed:
                            stage = "capture"
                        capture_failed = True
                        raise

                captured = capture()
                stage = "transcription"
                try:
                    result = await source.async_process_audio_stream(source_metadata, captured)
                finally:
                    await captured.aclose()
                    if close := getattr(iterator, "aclose", None):
                        await close()
                if capture_failed:
                    # A provider must not turn a rejected/oversized stream into
                    # an accepted partial recording by swallowing its exception.
                    raise ValueError("Recording was rejected")
                if not audio or len(audio) % 2:
                    stage = "audio_format"
                    raise ValueError("Unsupported PCM recording")
                clip = bytes(audio)
            if (
                result.result != stt.SpeechResultState.SUCCESS
                or not isinstance(result.text, str)
                or not result.text.strip()
                or len(result.text) > 5000
            ):
                raise ValueError("Control transcription unavailable")
            stage = "handoff"
            if self.runtime.authorize(connection, user.id) != login_id:
                raise ValueError("Phone login changed")
            self.runtime.frames.put(owner, clip, result.text)
            record("stt", "ready", control=control_category(result.text), audio_bytes=len(audio))
            return stt.SpeechResult(MARKER, stt.SpeechResultState.SUCCESS)
        except asyncio.CancelledError:
            record("stt", "cancelled", audio_bytes=len(audio), cancel_stage=stage)
            if owner is not None:
                self.runtime.frames.discard(owner)
            raise
        except Exception:  # noqa: BLE001 - Do not leak audio, peer errors or credentials into pipeline logs.
            record("stt", stage, audio_bytes=len(audio))
            if owner is not None:
                self.runtime.frames.discard(owner)
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        finally:
            audio.clear()
