"""Native cancellation recovery and real Wyoming provider over synthetic loopback."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import test_phone_learning_pipeline as phone_fixtures

phone = phone_fixtures.phone
pipeline_components = phone_fixtures.pipeline_components
LOGGER = "custom_components.codex_assist.learning.phone_diagnostics"


async def test_cancelled_prepare_reports_distinct_stage_without_audio(hass, phone, caplog):
    entered = asyncio.Event()

    async def blocked_prepare(*args):
        entered.set()
        await asyncio.Event().wait()

    with (
        caplog.at_level(logging.INFO, logger=LOGGER),
        patch.object(phone["runtime"].controller, "prepare", side_effect=blocked_prepare),
    ):
        task = asyncio.create_task(phone["run"](1, send_eof=False))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await phone_fixtures.close_phone_turn(hass, phone, phone["client"])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert any(
        "stage=stt result=cancelled" in entry.getMessage()
        and "audio_ms=0 cancel_stage=prepare" in entry.getMessage()
        for entry in caplog.records
        if entry.name == LOGGER
    )
    assert not phone["runtime"].frames.pending and not phone["runtime"].frames.busy
    assert not phone["backend"].active
    assert not [call for call in phone["backend"].calls if call[0] in {"begin", "sample"}]


async def test_zero_buffer_disconnect_keeps_saved_count_and_requires_new_notice(
    hass, hass_ws_client, phone, caplog
):
    await phone["run"](1)
    await phone["run"](2)
    await phone["run"](3)
    assert phone["backend"].count == 1
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def blocked_source(metadata, stream):
        # Source has been entered but has not consumed any audio from the client.
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with (
        caplog.at_level(logging.INFO, logger=LOGGER),
        patch.object(phone["source"], "async_process_audio_stream", side_effect=blocked_source),
    ):
        task = asyncio.create_task(phone["run"](3, send_eof=False))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await phone_fixtures.close_phone_turn(hass, phone, phone["client"])
            await asyncio.wait_for(cancelled.wait(), 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert any(
        "stage=stt result=cancelled" in entry.getMessage()
        and "audio_ms=0 cancel_stage=transcription" in entry.getMessage()
        for entry in caplog.records
        if entry.name == LOGGER
    )
    assert not phone["runtime"].frames.pending and not phone["runtime"].frames.busy
    assert not phone["runtime"].controller.flows
    assert not phone["backend"].active and phone["backend"].count == 1
    before = len(phone["backend"].calls)
    second = await hass_ws_client(hass)
    assert "no active voice learning session" in phone_fixtures.speech(
        await phone["run"](4, selected_client=second)
    )
    # First Start learning in a fresh scope is notice only, never fresh consent.
    assert "Before we begin" in phone_fixtures.speech(await phone["run"](2, selected_client=second))
    assert not [
        call
        for call in phone["backend"].calls[before:]
        if call[0] in {"begin", "sample", "resume", "discard"}
    ]
    assert phone["backend"].count == 1


@pytest.fixture
async def wyoming_loopback(phone):
    # Imports stay inside the newer-only fixture: older Codex matrix environments
    # do not install Wyoming or import the newer learning phone APIs.
    from homeassistant.components.wyoming.data import WyomingService
    from homeassistant.components.wyoming.stt import WyomingSttProvider
    from wyoming.asr import Transcript
    from wyoming.audio import AudioChunk, AudioStart, AudioStop
    from wyoming.event import async_read_event, async_write_event
    from wyoming.info import AsrModel, AsrProgram, Attribution, Info

    state = SimpleNamespace(
        mode="normal", received=[], tasks=set(), writers=set(), started=asyncio.Event()
    )

    async def serve(reader, writer):
        task = asyncio.current_task()
        state.tasks.add(task)
        state.writers.add(writer)
        clip = bytearray()
        try:
            while event := await async_read_event(reader):
                if AudioStart.is_type(event.type):
                    state.started.set()
                if AudioStart.is_type(event.type) and state.mode == "drop":
                    return
                if AudioChunk.is_type(event.type):
                    chunk = AudioChunk.from_event(event).audio
                    clip.extend(chunk)
                    if state.mode == "endpoint":
                        await async_write_event(Transcript("No").event(), writer)
                        # Drain in-flight upload bytes until the real provider
                        # closes. Closing immediately with unread TCP data sends
                        # a reset and tests a broken peer, not early endpointing.
                        await reader.read()
                        return
                if AudioStop.is_type(event.type):
                    text = {
                        1: "Learn my voice",
                        2: "Start learning",
                        3: "A reading phrase",
                        4: "Pause learning",
                    }[clip[0]]
                    await async_write_event(Transcript(text).event(), writer)
                    return
        finally:
            state.received.append(bytes(clip))
            writer.close()
            await writer.wait_closed()
            state.writers.discard(writer)
            state.tasks.discard(task)

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    attribution = Attribution(name="Synthetic", url="https://example.com")
    model = AsrModel(
        name="synthetic",
        attribution=attribution,
        installed=True,
        description="Loopback only",
        version="test",
        languages=["en"],
    )
    program = AsrProgram(
        name="synthetic",
        attribution=attribution,
        installed=True,
        description="No DSP or real Whisper",
        version="test",
        models=[model],
        requires_external_vad=False,
    )
    service = WyomingService("127.0.0.1", server.sockets[0].getsockname()[1], Info(asr=[program]))
    provider = WyomingSttProvider(phone["entry"], service)
    try:
        with patch.object(
            phone["source"], "async_process_audio_stream", provider.async_process_audio_stream
        ):
            yield state
    finally:
        server.close()
        await server.wait_closed()
        for writer in list(state.writers):
            writer.close()
        if state.tasks:
            await asyncio.wait_for(asyncio.gather(*list(state.tasks)), 2)


async def test_real_wyoming_provider_preserves_consent_upload_and_pause(phone, wyoming_loopback):
    assert "Before we begin" in phone_fixtures.speech(await phone["run"](1))
    assert not phone["backend"].active
    assert "Sample 1 of 2" in phone_fixtures.speech(await phone["run"](2))
    assert phone["backend"].count == 0
    assert "Sample 2 of 2" in phone_fixtures.speech(await phone["run"](3))
    assert "paused" in phone_fixtures.speech(await phone["run"](4))
    assert phone["backend"].count == 1 and not phone["backend"].active
    assert len([call for call in phone["backend"].calls if call[0] == "sample"]) == 1
    assert not phone["runtime"].frames.pending and not phone["runtime"].frames.busy
    assert len(wyoming_loopback.received) == 4


async def test_real_wyoming_endpoint_does_not_wait_for_client_eof(phone, wyoming_loopback):
    wyoming_loopback.mode = "endpoint"
    events = await asyncio.wait_for(phone["run"](5, send_eof=False), 2)
    assert "no active voice learning session" in phone_fixtures.speech(events)
    assert not phone["backend"].active and phone["backend"].count == 0
    assert not phone["runtime"].frames.pending and not phone["runtime"].frames.busy


async def test_real_wyoming_disconnect_never_submits_partial_sample(phone, wyoming_loopback):
    await phone["run"](1)
    await phone["run"](2)
    await phone["run"](3)
    before = len(phone["backend"].calls)
    wyoming_loopback.mode = "drop"
    await phone["run"](4, expect_error=True)
    assert phone["backend"].count == 1
    assert not [
        call
        for call in phone["backend"].calls[before:]
        if call[0] in {"sample", "begin", "resume", "discard"}
    ]
    assert not phone["runtime"].frames.pending and not phone["runtime"].frames.busy


async def test_real_wyoming_zero_audio_client_disconnect_keeps_saved_sample(
    hass, phone, wyoming_loopback, caplog
):
    from homeassistant.components import assist_pipeline

    await phone["run"](1)
    await phone["run"](2)
    await phone["run"](3)
    pipeline = next(
        p
        for p in assist_pipeline.async_get_pipelines(hass)
        if p.stt_engine == phone["engine"].entity_id
    )
    wyoming_loopback.started.clear()
    before = len(phone["backend"].calls)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await phone["client"].send_json(
            {
                "id": 2000,
                "type": "assist_pipeline/run",
                "pipeline": pipeline.id,
                "start_stage": "stt",
                "end_stage": "intent",
                "conversation_id": "phone-chat",
                "input": {"sample_rate": 16000},
            }
        )
        # Real Wyoming handshake and upload child task, but deliberately no PCM
        # from the native client before it disconnects.
        await asyncio.wait_for(wyoming_loopback.started.wait(), 2)
        await phone_fixtures.close_phone_turn(hass, phone, phone["client"])
        # Socket/phone cleanup can finish before Wyoming's upload/receive child
        # tasks have unwound. Await the observed cancellation, not a fixed delay.
        async with asyncio.timeout(2):
            while not any(
                "stage=stt result=cancelled" in entry.getMessage()
                for entry in caplog.records
                if entry.name == LOGGER
            ):
                await asyncio.sleep(0.01)
    assert any(
        "stage=stt result=cancelled" in entry.getMessage()
        and "audio_ms=0 cancel_stage=transcription" in entry.getMessage()
        for entry in caplog.records
        if entry.name == LOGGER
    )
    assert phone["backend"].count == 1 and not phone["backend"].active
    assert not phone["runtime"].frames.pending and not phone["runtime"].frames.busy
    assert not [
        call
        for call in phone["backend"].calls[before:]
        if call[0] in {"begin", "sample", "resume", "discard"}
    ]
