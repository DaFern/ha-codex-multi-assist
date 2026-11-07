"""Real loopback Wyoming transport and native HA handoff; no physical audio."""

import asyncio
import json
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from homeassistant.components import stt

from custom_components.codex_assist.entry_modules import learning_supported
from custom_components.codex_assist.voice_match import (
    CONF_CLEAN_TRANSCRIPT,
    CONF_VOICE_MATCH_HOST,
    CONF_VOICE_MATCH_PORT,
    runtime_for_entry,
)
from custom_components.codex_assist.voice_match_backend import PersonalBackend, endpoint
from tests_ha.test_clean_speaker_stt import event_data, packet
from tests_ha.test_clean_speaker_stt import managed as managed
from tests_ha.test_clean_speaker_stt import prototype as prototype

pytestmark = pytest.mark.skipif(not learning_supported(), reason="Requires HA 2026.10+")


@pytest.fixture
async def peer(socket_enabled):
    from wyoming.asr import Transcript
    from wyoming.audio import AudioChunk, AudioStart, AudioStop
    from wyoming.event import async_read_event, async_write_event
    from wyoming.info import AsrModel, AsrProgram, Attribution, Describe, Info

    attribution = Attribution(name="Synthetic", url="https://example.com")
    program = AsrProgram(
        name="voice-match-personal", description="Loopback only", attribution=attribution,
        installed=True, version="test", models=[AsrModel(
            name="synthetic", description="No speech model", attribution=attribution,
            installed=True, version="test", languages=["en"],
        )], requires_external_vad=False,
    )
    state = SimpleNamespace(program=program, mode="normal", packets={}, audio=[],
                            writers=set(), tasks=set(), started=asyncio.Event(), connections=0)

    async def serve(reader, writer):
        task = asyncio.current_task()
        state.tasks.add(task)
        state.writers.add(writer)
        state.connections += 1
        clip = bytearray()
        try:
            while event := await async_read_event(reader):
                if Describe.is_type(event.type):
                    await async_write_event(Info(asr=[state.program]).event(), writer)
                elif AudioStart.is_type(event.type):
                    state.started.set()
                    if state.mode == "drop":
                        return
                elif AudioChunk.is_type(event.type):
                    clip.extend(AudioChunk.from_event(event).audio)
                    if state.mode == "early":
                        await async_write_event(Transcript("early").event(), writer)
                        await reader.read()
                        return
                elif AudioStop.is_type(event.type):
                    if state.mode == "wait":
                        continue
                    text = state.packets.get(clip[0], "raw unverified words")
                    await async_write_event(Transcript(text).event(), writer)
                    return
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            state.audio.append(bytes(clip))
            writer.close()
            await writer.wait_closed()
            state.tasks.discard(task)
            state.writers.discard(writer)

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    state.options = {CONF_VOICE_MATCH_HOST: "127.0.0.1",
                     CONF_VOICE_MATCH_PORT: server.sockets[0].getsockname()[1]}
    try:
        yield state
    finally:
        server.close()
        await server.wait_closed()
        for task in list(state.tasks):
            task.cancel()
        await asyncio.gather(*state.tasks, return_exceptions=True)


def metadata():
    return stt.SpeechMetadata(
        language="en", format=stt.AudioFormats.WAV, codec=stt.AudioCodecs.PCM,
        bit_rate=stt.AudioBitRates.BITRATE_16, sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
        channel=stt.AudioChannels.CHANNEL_MONO,
    )


async def audio(marker=1):
    yield bytes([marker, 0]) * 32


@pytest.mark.parametrize("host, port", [
    ("http://example.com", 10352), ("user@example.com", 10352), ("bad host", 10352),
    ("-bad", 10352), ("example.com", True), ("example.com", 0), ("example.com", 65536),
])
async def test_endpoint_rejects_urls_credentials_and_invalid_ports(host, port):
    with pytest.raises(ValueError):
        endpoint({CONF_VOICE_MATCH_HOST: host, CONF_VOICE_MATCH_PORT: port})


async def test_probe_sends_no_audio_and_checks_actual_service(peer):
    backend = PersonalBackend(peer.options)
    assert await backend.async_refresh()
    assert backend.supported_languages == ["en"]
    assert not backend.audio_processing.requires_external_vad
    peer.program = replace(peer.program, name="voice-match")
    assert not await backend.async_refresh()
    assert not any(peer.audio)


async def test_source_replacement_is_rejected_before_audio(peer):
    backend = PersonalBackend(peer.options)
    assert await backend.async_refresh()
    peer.program = replace(peer.program, name="faster-whisper")
    consumed = False

    async def capture():
        nonlocal consumed
        consumed = True
        yield b"\x00\x00"

    result = await backend.async_process_audio_stream(metadata(), capture())
    assert result.result is stt.SpeechResultState.ERROR
    assert not consumed and not backend.available


async def test_audio_transported_once_and_backend_loss_recovers(peer):
    backend = PersonalBackend(peer.options)
    peer.packets[1] = "synthetic response"
    result = await backend.async_process_audio_stream(metadata(), audio())
    assert result.text == "synthetic response"
    assert [clip for clip in peer.audio if clip] == [bytes([1, 0]) * 32]
    peer.mode = "drop"
    result = await backend.async_process_audio_stream(metadata(), audio())
    assert result.result is stt.SpeechResultState.ERROR
    assert not backend.available
    peer.mode = "normal"
    assert await backend.async_refresh()


async def test_early_result_closes_capture_and_does_not_wait_for_eof(peer):
    peer.mode = "early"
    closed = asyncio.Event()

    async def capture():
        try:
            yield b"\x01\x00"
            await asyncio.Event().wait()
        finally:
            closed.set()

    backend = PersonalBackend(peer.options)
    async with asyncio.timeout(2):
        result = await backend.async_process_audio_stream(metadata(), capture())
    assert result.text == "early" and closed.is_set()


async def test_cancellation_closes_capture_and_propagates(peer):
    closed = asyncio.Event()

    async def capture():
        try:
            yield b"\x01\x00"
            await asyncio.Event().wait()
        finally:
            closed.set()

    backend = PersonalBackend(peer.options)
    task = asyncio.create_task(backend.async_process_audio_stream(metadata(), capture()))
    await peer.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


async def test_request_timeout_is_bounded_without_retry(peer, monkeypatch):
    monkeypatch.setattr("custom_components.codex_assist.voice_match_backend.REQUEST_TIMEOUT", 0.05)
    peer.mode = "wait"
    backend = PersonalBackend(peer.options)
    result = await backend.async_process_audio_stream(metadata(), audio())
    assert result.result is stt.SpeechResultState.ERROR and result.text is None
    assert peer.connections == 1
    assert not backend.available


@pytest.mark.parametrize("kind", ["oversized", "interrupted", "unaligned"])
async def test_bad_audio_never_returns_partial_success(peer, kind):
    async def capture():
        if kind == "oversized":
            yield b"\x00" * (16000 * 2 * 60 + 1)
        elif kind == "unaligned":
            yield b"\x01"
        else:
            yield b"\x01\x00"
            raise RuntimeError("private capture error")

    backend = PersonalBackend(peer.options)
    result = await backend.async_process_audio_stream(metadata(), capture())
    assert result.result is stt.SpeechResultState.ERROR and result.text is None
    assert peer.connections == 1


@pytest.fixture
async def direct(prototype, peer, hass, monkeypatch):
    from homeassistant.components import assist_pipeline
    from homeassistant.helpers import entity_registry as er

    p = prototype
    hass.config_entries.async_update_entry(p.entry, options={
        **p.entry.options, **peer.options, CONF_CLEAN_TRANSCRIPT: True,
    })
    await hass.async_block_till_done()
    registered = [item for item in er.async_entries_for_config_entry(
        er.async_get(hass), p.entry.entry_id,
    ) if item.domain == "stt"]
    assert len(registered) == 1
    item = registered[0]
    assert item.unique_id == p.entry.entry_id + "_voice_match_clean_stt"
    adapter = stt.async_get_speech_to_text_entity(hass, item.entity_id)
    assert adapter.available and adapter.name == "Voice Match"
    p.adapter = adapter
    pipeline = replace(p.pipeline, stt_engine=item.entity_id)
    monkeypatch.setattr(assist_pipeline, "async_get_pipeline", lambda *args, **kwargs: pipeline)
    return p


@pytest.mark.parametrize("instructions", ["", "Private style"])
async def test_direct_native_pipeline_has_one_stt_and_preserves_context(
    direct, peer, hass, instructions,
):
    p = direct
    peer.packets[1] = packet(p.key, instructions=instructions, speaker_name="Alice")
    events = await p.run(1)
    assert not [event for event in events if event.type == "error"]
    assert event_data(events, "stt-end")["stt_output"]["text"] == "hello"
    serialized = json.dumps([asdict(event) for event in events])
    for private in (p.key, "Alice", "[[voice-match:", "Private style"):
        assert private not in serialized
    assert '"Alice"' in p.calls[-1]["instructions"]
    if instructions:
        assert instructions in p.calls[-1]["instructions"]
    assert not runtime_for_entry(p.entry).handoffs.pending
    # The direct connection registers no Wyoming source as a side effect.
    assert not hass.config_entries.async_entries("wyoming")

    peer.packets[2] = packet(p.key, voice="alice", instructions="", speaker_name="Alice")
    peer.packets[3] = packet(p.key, voice="bob", instructions="", speaker_name="Bob")
    concurrent = await asyncio.gather(p.run(2), p.run(3))
    assert all(event_data(events, "stt-end")["stt_output"]["text"] == "hello"
               for events in concurrent)
    prompts = [call["instructions"] for call in p.calls[-2:]]
    assert sum('"Alice"' in prompt for prompt in prompts) == 1
    assert sum('"Bob"' in prompt for prompt in prompts) == 1


@pytest.mark.parametrize("result", ["plain", "wrong_key", "empty"])
async def test_direct_unverified_packets_never_reach_model(direct, peer, result):
    from cryptography.fernet import Fernet

    wire = {"plain": "raw words", "wrong_key": packet(Fernet.generate_key().decode()), "empty": ""}
    peer.packets[1] = wire[result]
    events = await direct.run(1)
    assert [event for event in events if event.type == "error"]
    assert not direct.calls
    assert not runtime_for_entry(direct.entry).handoffs.pending
    assert "[[voice-match:" not in json.dumps([asdict(event) for event in events])


async def test_direct_unload_cancels_native_request_and_owned_tasks(direct, peer, hass):
    peer.mode = "wait"
    task = asyncio.create_task(direct.run(1))
    await peer.started.wait()
    assert await hass.config_entries.async_unload(direct.entry.entry_id)
    with pytest.raises(asyncio.CancelledError):
        await task
    runtime = runtime_for_entry(direct.entry)
    assert not runtime.clean_tasks and not runtime.handoffs.pending
    assert not direct.adapter.available and not direct.calls


async def test_direct_backend_metadata_loss_and_recovery_preserve_codex(direct, peer, hass):
    program = peer.program
    peer.program = replace(program, name="ordinary-whisper")
    await direct.adapter._refresh_backend(None)
    assert not direct.adapter.available
    assert hass.states.get("conversation.codex_assist").state != "unavailable"
    assert hass.states.get("ai_task.codex_assist_ai_task").state != "unavailable"
    peer.program = program
    await direct.adapter._refresh_backend(None)
    assert direct.adapter.available


async def test_invalid_saved_endpoint_only_disables_stt(direct, hass):
    hass.config_entries.async_update_entry(direct.entry, options={
        **direct.entry.options, CONF_VOICE_MATCH_HOST: "http://invalid.example",
    })
    await hass.async_block_till_done()
    adapter = stt.async_get_speech_to_text_entity(hass, direct.adapter.entity_id)
    assert adapter is not None and not adapter.available
    assert hass.states.get("conversation.codex_assist").state != "unavailable"
    assert hass.states.get("ai_task.codex_assist_ai_task").state != "unavailable"


async def test_migration_keeps_existing_entity_and_pipeline_binding(managed, peer, hass):
    from custom_components.codex_assist.voice_match import CONF_PERSONAL_STT_SOURCE

    old = managed.adapter
    options = {**managed.entry.options, **peer.options}
    options.pop(CONF_PERSONAL_STT_SOURCE)
    peer.packets[1] = packet(managed.key, speaker_name="Alice")
    hass.config_entries.async_update_entry(managed.entry, options=options)
    await hass.async_block_till_done()
    current = stt.async_get_speech_to_text_entity(hass, old.entity_id)
    assert current is not old and current.available and not old.available
    assert current.unique_id == old.unique_id
    events = await managed.run(1)
    assert event_data(events, "stt-end")["stt_output"]["text"] == "hello"
    assert '"Alice"' in managed.calls[-1]["instructions"]


async def test_real_options_probe_and_reload_create_only_one_stt(prototype, peer, hass):
    from homeassistant.data_entry_flow import FlowResultType
    from homeassistant.helpers import entity_registry as er

    result = await hass.config_entries.options.async_init(prototype.entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "voice_match"},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"enabled": True, **peer.options},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    engines = [item for item in er.async_entries_for_config_entry(
        er.async_get(hass), prototype.entry.entry_id,
    ) if item.domain == "stt"]
    assert len(engines) == 1
    assert stt.async_get_speech_to_text_entity(hass, engines[0].entity_id).available
    assert not any(peer.audio)
    assert not hass.config_entries.async_entries("wyoming")
