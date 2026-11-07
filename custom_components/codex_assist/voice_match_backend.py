"""Private Wyoming transport, without registering a second STT entity.

Describe checks service compatibility only. The existing request-bound packet
verification, not the service name or address, establishes trusted context.
"""

import asyncio
import ipaddress
import re

from homeassistant.components import stt

from .voice_match import CONF_VOICE_MATCH_HOST, CONF_VOICE_MATCH_PORT

MAX_AUDIO_BYTES = 16000 * 2 * 60
PROBE_TIMEOUT = 5
REQUEST_TIMEOUT = 105


def endpoint(options):
    """Validate an explicit host/port, never a URL or embedded credentials."""
    host = options.get(CONF_VOICE_MATCH_HOST)
    port = options.get(CONF_VOICE_MATCH_PORT, 10352)
    if not isinstance(host, str) or not host or len(host) > 253:
        raise ValueError("Invalid Voice Match host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", part)
               for part in host.split(".")):
            raise ValueError("Invalid Voice Match host") from None
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid Voice Match port")
    return host, port


async def async_backend(hass, options):
    """Load Core's own protocol dependency, without creating a Wyoming entry.

    This avoids imposing a conflicting Wyoming version on older Codex-only HA
    installations. Only explicitly configuring direct Voice Match needs it.
    """
    from homeassistant.setup import async_setup_component

    backend = PersonalBackend(options)
    if not await async_setup_component(hass, "wyoming", {}):
        raise ValueError("Wyoming protocol unavailable")
    await backend.async_refresh()
    return backend


class PersonalBackend:
    """Non-entity source. Each request owns its connection and upload tasks."""

    supported_formats = [stt.AudioFormats.WAV]
    supported_codecs = [stt.AudioCodecs.PCM]
    supported_bit_rates = [stt.AudioBitRates.BITRATE_16]
    supported_sample_rates = [stt.AudioSampleRates.SAMPLERATE_16000]
    supported_channels = [stt.AudioChannels.CHANNEL_MONO]

    def __init__(self, options):
        self.endpoint = endpoint(options)
        self.available = False
        self.supported_languages = []
        self.audio_processing = stt.SpeechAudioProcessing(True, False, False)

    async def _describe(self, client):
        from wyoming.info import Describe, Info

        await client.write_event(Describe().event())
        event = await client.read_event()
        if event is None or not Info.is_type(event.type):
            raise ValueError("Voice Match backend unavailable")
        info = Info.from_event(event)
        if len(info.asr) != 1 or info.asr[0].name != "voice-match-personal":
            raise ValueError("Select the personalised Voice Match backend")
        program = info.asr[0]
        languages = sorted({language for model in program.models if model.installed
                            for language in model.languages})
        if not languages:
            raise ValueError("Voice Match backend has no languages")
        self.supported_languages = languages
        self.audio_processing = stt.SpeechAudioProcessing(
            requires_external_vad=program.requires_external_vad,
            prefers_auto_gain_enabled=program.prefers_auto_gain_enabled,
            prefers_noise_reduction_enabled=program.prefers_noise_reduction_enabled,
        )
        self.available = True

    async def async_refresh(self):
        """Metadata-only availability probe. Never record or send audio."""
        from wyoming.client import AsyncTcpClient

        try:
            async with asyncio.timeout(PROBE_TIMEOUT), AsyncTcpClient(*self.endpoint) as client:
                await self._describe(client)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.available = False
        return self.available

    async def async_process_audio_stream(self, metadata, stream):
        from wyoming.asr import Transcribe, Transcript
        from wyoming.audio import AudioChunk, AudioStart, AudioStop
        from wyoming.client import AsyncTcpClient
        from wyoming.error import Error

        async def upload(client):
            iterator = aiter(stream)
            size = 0
            try:
                async for audio in iterator:
                    if not isinstance(audio, bytes):
                        raise ValueError("Invalid audio")
                    size += len(audio)
                    if size > MAX_AUDIO_BYTES:
                        raise ValueError("Audio exceeds sixty seconds")
                    await client.write_event(AudioChunk(
                        rate=16000, width=2, channels=1, audio=audio,
                    ).event())
                if size == 0 or size % 2:
                    raise ValueError("Invalid audio")
                await client.write_event(AudioStop().event())
            finally:
                if close := getattr(iterator, "aclose", None):
                    await close()

        async def receive(client):
            while True:
                event = await client.read_event()
                if event is None or Error.is_type(event.type):
                    raise ValueError("Voice Match transcription unavailable")
                if Transcript.is_type(event.type):
                    return stt.SpeechResult(
                        Transcript.from_event(event).text, stt.SpeechResultState.SUCCESS,
                    )

        try:
            if (metadata.format not in self.supported_formats
                    or metadata.codec not in self.supported_codecs
                    or metadata.bit_rate not in self.supported_bit_rates
                    or metadata.sample_rate not in self.supported_sample_rates
                    or metadata.channel not in self.supported_channels):
                raise ValueError("Unsupported audio format")
            async with asyncio.timeout(REQUEST_TIMEOUT), AsyncTcpClient(*self.endpoint) as client:
                # Revalidate the peer on this exact connection before sending audio.
                async with asyncio.timeout(PROBE_TIMEOUT):
                    await self._describe(client)
                if metadata.language not in self.supported_languages:
                    raise ValueError("Unsupported language")
                await client.write_event(Transcribe(language=metadata.language).event())
                await client.write_event(AudioStart(rate=16000, width=2, channels=1).event())
                sending = asyncio.create_task(upload(client))
                receiving = asyncio.create_task(receive(client))
                tasks = (sending, receiving)
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    # An upload failure must never become a partial success.
                    if sending in done:
                        sending.result()
                    if receiving in done:
                        return receiving.result()
                    return await receiving
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never expose peer errors, transcripts, headers or credentials.
            self.available = False
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
