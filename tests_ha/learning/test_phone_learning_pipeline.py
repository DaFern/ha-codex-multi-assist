"""Actual phone WebSocket pipeline with synthetic Whisper/backend boundaries."""

import asyncio
import base64
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from homeassistant.components import conversation, stt
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

# Reuse only the isolated pipeline/DSP fixture, never its fake learning entities
# as the implementation under test. Production learning entities are loaded below.
from test_learning_pipeline_feasibility import pipeline_components  # noqa: F401 - pytest fixture

from custom_components.codex_assist.learning import DOMAIN
from custom_components.codex_assist.learning.phone_flow import (
    INTRO,
    MARKER,
    NOTICE,
    PRIVACY_DETAILS,
)


@dataclass
class Backend:
    user_id: str
    count: int = 0
    active: bool = False
    calls: list = field(default_factory=list)
    notice: bool = False
    permit_serial: int = 0
    current_permit: str | None = None
    permit_count: int | None = None

    async def call(self, operation, user_id, data):
        self.calls.append((operation, user_id, data))
        if operation == "hello":
            return {"ready": True}
        if operation == "own_profile":
            return {"id": "assigned-profile" if user_id == self.user_id else None}
        assert user_id == self.user_id
        if operation == "begin":
            assert data["own_only"] is True
            self.active = True
            return {"session_token": "synthetic-session", "expires_in": 900}
        if operation == "cancel":
            self.active = False
            return {"outcome": "paused"}
        if operation == "discard":
            assert data["confirm"] is True
            self.active = False
            self.count = 0
            return {"outcome": "cancelled"}
        assert data["session_token"] == "synthetic-session"
        if operation == "resume_preview":
            assert not self.active
            return {"id": "assigned-profile", "count": self.count, "target": 2}
        if operation == "resume":
            assert not self.active and data["consent"] is True
            assert data["count"] == self.count and data["target"] == 2
            self.active = True
            return {"session_token": "synthetic-session", "expires_in": 900}
        if operation == "permit":
            self.permit_serial += 1
            self.current_permit = f"synthetic-permit-{self.permit_serial}"
            self.permit_count = self.count
            return {
                "permit": self.current_permit,
                "count": self.count,
                "prompt": "The bright morning sun is shining through the kitchen window "
                "while I make breakfast.",
            }
        if operation == "sample":
            assert data["permit"] == self.current_permit and self.permit_count == self.count
            self.current_permit = None
            audio = base64.b64decode(data["audio"])
            self.notice = len(audio) < 32000
            if not self.notice:
                self.count += 1
            return {"queued": True}
        if operation == "state":
            return {
                "id": "assigned-profile",
                "outcome": "complete" if self.count == 2 else "active",
                "processing": False,
                "count": self.count,
                "target": 2,
                "error": False,
                "notice": self.notice,
            }
        raise AssertionError("Unexpected operation")


@pytest.fixture
async def phone(hass, hass_ws_client, hass_admin_user, pipeline_components):  # noqa: F811 - imported pytest fixture
    source_calls = []

    class Whisper(stt.SpeechToTextEntity):
        _attr_name = "Synthetic ordinary Whisper"
        _attr_unique_id = "ordinary-whisper-source"
        supported_languages: ClassVar[list[str]] = ["en"]
        supported_formats: ClassVar[list[stt.AudioFormats]] = [stt.AudioFormats.WAV]
        supported_codecs: ClassVar[list[stt.AudioCodecs]] = [stt.AudioCodecs.PCM]
        supported_bit_rates: ClassVar[list[stt.AudioBitRates]] = [stt.AudioBitRates.BITRATE_16]
        supported_sample_rates: ClassVar[list[stt.AudioSampleRates]] = [
            stt.AudioSampleRates.SAMPLERATE_16000
        ]
        supported_channels: ClassVar[list[stt.AudioChannels]] = [stt.AudioChannels.CHANNEL_MONO]
        audio_processing = stt.SpeechAudioProcessing(False, False, False)

        async def async_process_audio_stream(self, metadata, stream):
            clip = b"".join([chunk async for chunk in stream])
            source_calls.append(clip)
            text = {
                1: "start",
                2: "Start learning.",
                3: "A varied natural reading phrase",
                4: "Pause",
                5: "No",
                6: "status",
                7: "No,",
                8: NOTICE,
                9: "Yes",
                10: "Start voice learning",
                11: "Learn my voice",
                12: "Cancel learning",
                13: "Pause, learning.",
                14: "Please cancel learning!",
                15: "Paws learning",
                16: "Don't cancel learning",
                17: "Cancel learning cancel learning",
                18: "Continue learning",
                19: "Privacy details",
            }[clip[0]]
            return stt.SpeechResult(text, stt.SpeechResultState.SUCCESS)

    source = Whisper()
    await hass.data[stt.DOMAIN].async_add_entities([source])

    class WyomingProviderPlatform:
        platform_name = "wyoming"

        def __init__(self, original):
            self.original = original

        def __getattr__(self, name):
            return getattr(self.original, name)

    source.platform = WyomingProviderPlatform(
        source.platform
    )  # Provider metadata stand-in; no real Wyoming I/O.
    assert await async_setup_component(hass, DOMAIN, {})
    backend = Backend(hass_admin_user.id)

    async def call(client, operation, user_id, data):
        return await backend.call(operation, user_id, data)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "module": "voice_match",
            "url": "http://addon:8099",
            "key": Fernet.generate_key().decode(),
        },
        options={"phone_enabled": True, "control_stt_engine": source.entity_id},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.codex_assist.learning.bridge_client.BridgeClient.call", call):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        from custom_components.codex_assist.learning.conversation import (
            PhoneLearningAgent,
        )
        from custom_components.codex_assist.learning.stt import PhoneLearningStt

        engine = next(
            entity
            for entity in hass.data[stt.DOMAIN].entities
            if isinstance(entity, PhoneLearningStt)
        )
        agent = next(
            entity
            for entity in hass.data[conversation.DOMAIN].entities
            if isinstance(entity, PhoneLearningAgent)
        )
        client = await hass_ws_client(hass)
        await client.send_json(
            {
                "id": 1,
                "type": "assist_pipeline/pipeline/create",
                "name": "Voice Learning test",
                "language": "en",
                "conversation_engine": agent.entity_id,
                "conversation_language": "en",
                "stt_engine": engine.entity_id,
                "stt_language": "en",
                "tts_engine": None,
                "tts_language": None,
                "tts_voice": None,
                "wake_word_entity": None,
                "wake_word_id": None,
                "prefer_local_intents": False,
            }
        )
        created = await client.receive_json()
        assert created["success"], created
        pipeline_id = created["result"]["id"]
        sequence = 10

        async def run(
            marker,
            *,
            selected_client=None,
            end_stage="intent",
            chat="phone-chat",
            expect_error=False,
            send_eof=True,
            sample_count=16000,
        ):
            nonlocal sequence
            current = selected_client or client
            sequence += 1
            await current.send_json(
                {
                    "id": sequence,
                    "type": "assist_pipeline/run",
                    "pipeline": pipeline_id,
                    "start_stage": "stt",
                    "end_stage": end_stage,
                    "conversation_id": chat,
                    "input": {"sample_rate": 16000},
                }
            )
            events = []
            while True:
                result = await asyncio.wait_for(current.receive_json(), 5)
                assert result.get("success", True), result
                if "event" not in result:
                    continue
                event = result["event"]
                events.append(event)
                if event["type"] == "run-start":
                    handler = event["data"]["runner_data"]["stt_binary_handler_id"]
                    await current.send_bytes(bytes([handler]) + bytes([marker, 0]) * sample_count)
                    if send_eof:
                        await current.send_bytes(bytes([handler]))
                if event["type"] == "run-end":
                    errors = [item for item in events if item["type"] == "error"]
                    assert bool(errors) == expect_error, events
                    return events

        yield {
            "run": run,
            "client": client,
            "entry": entry,
            "backend": backend,
            "agent": agent,
            "engine": engine,
            "source": source,
            "source_calls": source_calls,
            "runtime": entry.runtime_data.phone,
        }
        assert await hass.config_entries.async_unload(entry.entry_id)


def speech(events):
    return next(
        event["data"]["intent_output"]["response"]["speech"]["plain"]["speech"]
        for event in events
        if event["type"] == "intent-end"
    )


async def test_phone_uses_real_learning_entities_and_only_post_consent_audio_is_submitted(phone):
    assert "Before we begin" in speech(await phone["run"](1))
    assert not phone["backend"].active
    assert "Sample 1 of 2" in speech(await phone["run"](2))
    assert phone["backend"].count == 0
    assert "Sample 2 of 2" in speech(await phone["run"](3))
    assert phone["backend"].count == 1
    assert "complete" in speech(await phone["run"](3))
    assert phone["backend"].count == 2
    assert len([call for call in phone["backend"].calls if call[0] == "sample"]) == 2


async def test_native_launch_phrases_and_yes_are_not_consent(phone):
    assert "Before we begin" in speech(await phone["run"](2))
    assert not phone["backend"].active
    for marker in (9, 10, 11, 8):
        assert "If you're happy to continue" in speech(await phone["run"](marker))
        assert not phone["backend"].active
    assert "Sample 1 of 2" in speech(await phone["run"](2))
    assert phone["backend"].count == 0
    assert "cancelled" in speech(await phone["run"](12))
    assert phone["backend"].count == 0
    assert not phone["backend"].active


async def test_native_pause_is_not_submitted_as_a_sample(phone):
    await phone["run"](1)
    await phone["run"](2)
    assert "paused" in speech(await phone["run"](4))
    assert phone["backend"].count == 0
    assert not phone["backend"].active


@pytest.mark.parametrize("marker", [13, 15, 16, 17])
async def test_native_normalised_or_ambiguous_controls_pause_without_upload(phone, marker):
    await phone["run"](1)
    await phone["run"](2)
    assert "Sample 2 of 2" in speech(await phone["run"](3))
    assert "paused" in speech(await phone["run"](marker))
    assert phone["backend"].count == 1
    assert len([call for call in phone["backend"].calls if call[0] == "sample"]) == 1
    assert not [call for call in phone["backend"].calls if call[0] == "discard"]


async def test_native_cancel_discards_but_pause_preserves_samples(phone):
    await phone["run"](1)
    await phone["run"](2)
    await phone["run"](3)
    assert "paused" in speech(await phone["run"](13))
    assert phone["backend"].count == 1
    assert "Welcome back" in speech(await phone["run"](1))
    assert "Sample 2 of 2" in speech(await phone["run"](18))
    assert "deleted" in speech(await phone["run"](14))
    assert phone["backend"].count == 0
    assert not phone["backend"].active
    assert len([call for call in phone["backend"].calls if call[0] == "sample"]) == 1
    assert len([call for call in phone["backend"].calls if call[0] == "discard"]) == 1


async def test_other_login_cannot_train_even_with_the_same_user_and_chat(
    hass, hass_ws_client, hass_admin_user, phone
):
    await phone["run"](1)
    await phone["run"](2)
    login = await hass.auth.async_create_refresh_token(
        hass_admin_user, client_id="http://other-phone-login"
    )
    second = await hass_ws_client(hass, hass.auth.async_create_access_token(login))
    assert "Before we begin" in speech(await phone["run"](3, selected_client=second))
    assert phone["backend"].count == 0


async def test_native_trigger_interception_never_submits_or_creates_a_session(hass, phone):
    from homeassistant.components.conversation.agent_manager import get_agent_manager

    async def intercept(user_input, result):
        return "Synthetic trigger intercepted the marker"

    remove = get_agent_manager(hass).register_trigger(
        sentences=[MARKER], trigger_callback=intercept
    )
    try:
        await phone["run"](1)
        assert not phone["runtime"].frames.pending
        assert not phone["backend"].active
        assert not [call for call in phone["backend"].calls if call[0] == "begin"]
    finally:
        remove()


async def test_stt_only_and_typed_marker_never_train(phone):
    await phone["run"](3, end_stage="stt")
    assert not phone["runtime"].frames.pending
    await phone["client"].send_json(
        {
            "id": 100,
            "type": "conversation/process",
            "text": MARKER,
            "agent_id": phone["agent"].entity_id,
            "conversation_id": "phone-chat",
            "language": "en",
        }
    )
    result = await phone["client"].receive_json()
    assert result["success"]
    assert phone["backend"].count == 0
    assert not phone["backend"].active


async def test_phone_options_reject_no_source_and_the_learning_engine(hass, phone):
    entry = MockConfigEntry(domain=DOMAIN, data=phone["entry"].data)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "learning_menu"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "learning_phone"}
    )
    assert result["step_id"] == "learning_phone"
    for source in (None, phone["engine"].entity_id):
        data = {"phone_enabled": True}
        if source:
            data["control_stt_engine"] = source
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=data
        )
        assert result["errors"] == {"base": "invalid_stt_source"}


async def test_phone_options_retain_existing_source_when_omitted(hass, phone):
    result = await hass.config_entries.options.async_init(phone["entry"].entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "learning_phone"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"phone_enabled": True}
    )
    assert result["type"] == "create_entry"
    assert result["data"]["control_stt_engine"] == phone["source"].entity_id
    await hass.async_block_till_done()


async def test_completed_turn_disconnect_retains_only_bounded_guided_state(hass, phone):
    await phone["run"](1)
    await phone["run"](2)
    assert phone["backend"].active
    await phone["client"].close()
    await hass.async_block_till_done()
    tasks = list(phone["runtime"].cleanup_tasks)
    if tasks:
        import asyncio

        await asyncio.gather(*tasks)
    assert not phone["runtime"].connections
    assert not phone["runtime"].frames.pending
    flow = next(iter(phone["runtime"].controller.flows.values()))
    assert flow.connection is None
    assert flow.permit is None
    assert not flow.must_reconsent
    assert phone["backend"].active


async def test_native_diagnostics_distinguish_repeated_notice_from_recognised_no(phone, caplog):
    import logging

    logger = "custom_components.codex_assist.learning.phone_diagnostics"
    with caplog.at_level(logging.INFO, logger=logger):
        await phone["run"](1)
        assert "Before we begin" in speech(await phone["run"](8))
        assert "No learning started" in speech(await phone["run"](7))
    records = [entry for entry in caplog.records if entry.name == logger]
    output = "\n".join(entry.getMessage() for entry in records)
    assert "control=notice_like continuity=same_scope phase=consent" in output
    assert "control=stop continuity=same_scope phase=consent" in output
    assert "result=notice_repeat" in output
    assert "result=cancel_before_start" in output
    assert "stage=stt result=ready" in output
    assert "audio_ms=1000" in output
    login_id = next(iter(phone["runtime"].connections.values()))[0].refresh_token_id
    for private in (
        phone["entry"].data["key"],
        phone["backend"].user_id,
        login_id,
        "phone-chat",
        NOTICE,
        "No,",
    ):
        assert private not in repr([entry.__dict__ for entry in records])
    assert not [call for call in phone["backend"].calls if call[0] in {"begin", "sample"}]


async def test_native_diagnostics_report_stt_only_discard_and_typed_marker_missing(phone, caplog):
    import logging

    logger = "custom_components.codex_assist.learning.phone_diagnostics"
    with caplog.at_level(logging.INFO, logger=logger):
        await phone["run"](3, end_stage="stt")
        await phone["client"].send_json(
            {
                "id": 100,
                "type": "conversation/process",
                "text": MARKER,
                "agent_id": phone["agent"].entity_id,
                "conversation_id": "phone-chat",
                "language": "en",
            }
        )
        result = await phone["client"].receive_json()
        assert result["success"]
    output = "\n".join(entry.getMessage() for entry in caplog.records if entry.name == logger)
    assert "stage=handoff result=discarded" in output
    assert "stage=handoff result=missing" in output
    assert "stage=agent result=missing" in output
    assert not phone["backend"].active


async def test_native_diagnostics_report_transcription_failure_without_peer_error_or_clip(
    phone, caplog
):
    import logging

    logger = "custom_components.codex_assist.learning.phone_diagnostics"
    private = "PRIVATE-peer-transcript-and-credentials"

    async def fail_after_capture(metadata, stream):
        async for _ in stream:
            pass
        raise RuntimeError(private)

    with (
        caplog.at_level(logging.INFO, logger=logger),
        patch.object(phone["source"], "async_process_audio_stream", side_effect=fail_after_capture),
    ):
        await phone["run"](1, expect_error=True)
    output = "\n".join(entry.getMessage() for entry in caplog.records if entry.name == logger)
    assert "stage=stt result=transcription" in output
    assert "audio_ms=1000" in output
    assert private not in caplog.text
    assert not phone["runtime"].frames.pending
    assert not phone["backend"].active


async def test_source_can_endpoint_without_waiting_for_client_eof(phone):
    consumed = []

    async def endpoint(metadata, stream):
        # A streaming provider may finish on its own VAD. Companion stops sending
        # only after STT_END, so waiting for client EOF first would deadlock.
        async for chunk in stream:
            consumed.append(chunk)
            if sum(map(len, consumed)) >= 32000:
                break
        return stt.SpeechResult("No", stt.SpeechResultState.SUCCESS)

    with patch.object(phone["source"], "async_process_audio_stream", side_effect=endpoint):
        events = await asyncio.wait_for(phone["run"](5, send_eof=False), 1)
    assert "no active voice learning session" in speech(events)
    assert b"".join(consumed) == bytes([5, 0]) * 16000
    assert not phone["runtime"].frames.pending
    assert not phone["backend"].active


async def test_companion_style_reconnect_retains_notice_for_same_authenticated_login(
    hass, hass_ws_client, phone
):
    await phone["run"](1)
    await phone["client"].close()
    await hass.async_block_till_done()
    tasks = list(phone["runtime"].cleanup_tasks)
    if tasks:
        await asyncio.gather(*tasks)
    second = await hass_ws_client(hass)
    assert "Sample 1 of 2" in speech(await phone["run"](2, selected_client=second))
    assert phone["backend"].active
    assert not [call for call in phone["backend"].calls if call[0] == "sample"]


async def test_early_endpoint_hands_off_only_audio_consumed_by_source(phone):
    await phone["run"](1)
    await phone["run"](2)

    async def endpoint(metadata, stream):
        size = 0
        async for chunk in stream:
            size += len(chunk)
            if size >= 32000:
                break
        return stt.SpeechResult("A synthetic reading phrase", stt.SpeechResultState.SUCCESS)

    with patch.object(phone["source"], "async_process_audio_stream", side_effect=endpoint):
        events = await asyncio.wait_for(phone["run"](3, send_eof=False, sample_count=32000), 1)
    assert "Sample 2 of 2" in speech(events)
    samples = [call for call in phone["backend"].calls if call[0] == "sample"]
    assert len(samples) == 1
    assert base64.b64decode(samples[0][2]["audio"]) == bytes([3, 0]) * 16000
    assert not phone["runtime"].frames.pending


@pytest.mark.parametrize("swallow_limit", [False, True])
async def test_streaming_still_rejects_overlong_audio_even_if_source_swallows_error(
    phone, swallow_limit
):
    async def source(metadata, stream):
        try:
            async for _ in stream:
                pass
        except ValueError:
            if not swallow_limit:
                raise
        return stt.SpeechResult("Start learning", stt.SpeechResultState.SUCCESS)

    with patch.object(phone["source"], "async_process_audio_stream", side_effect=source):
        await phone["run"](2, sample_count=176000, expect_error=True)
    assert not phone["runtime"].frames.pending
    assert not phone["backend"].active
    assert not [call for call in phone["backend"].calls if call[0] in {"begin", "sample"}]


async def test_disconnect_cancels_streaming_source_and_drops_audio(hass, phone):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def source(metadata, stream):
        await anext(aiter(stream))
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with patch.object(phone["source"], "async_process_audio_stream", side_effect=source):
        task = asyncio.create_task(phone["run"](1, send_eof=False))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await phone["client"].close()
            await asyncio.wait_for(cancelled.wait(), 1)
            await hass.async_block_till_done()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert not phone["runtime"].frames.pending
    assert not phone["runtime"].frames.busy
    assert not phone["backend"].active


async def test_source_upload_child_task_does_not_change_native_handoff_owner(phone):
    async def source(metadata, stream):
        async def upload():
            return b"".join([chunk async for chunk in stream])

        audio = await asyncio.create_task(upload())
        assert audio == bytes([5, 0]) * 16000
        return stt.SpeechResult("No", stt.SpeechResultState.SUCCESS)

    with patch.object(phone["source"], "async_process_audio_stream", side_effect=source):
        assert "no active voice learning session" in speech(await phone["run"](5))
    assert not phone["runtime"].frames.pending
    assert not phone["backend"].active


async def test_source_cannot_accept_audio_it_never_consumed(phone):
    async def source(metadata, stream):
        return stt.SpeechResult("Start learning", stt.SpeechResultState.SUCCESS)

    with patch.object(phone["source"], "async_process_audio_stream", side_effect=source):
        await phone["run"](2, expect_error=True)
    assert not phone["runtime"].frames.pending
    assert not phone["backend"].active


async def test_authenticated_login_session_can_be_distinguished_from_socket_and_account(
    hass,
    hass_ws_client,
    hass_admin_user,
    phone,
):
    # Feasibility only: production flow binding is deliberately unchanged.
    from homeassistant.components.websocket_api.connection import current_connection

    bindings = []

    async def source(metadata, stream):
        async for _ in stream:
            pass
        connection = current_connection.get()
        token_id = connection.refresh_token_id
        token = hass.auth.async_get_refresh_token(token_id)
        assert token is not None and token.user.id == hass_admin_user.id
        bindings.append(token_id)
        return stt.SpeechResult("No", stt.SpeechResultState.SUCCESS)

    with patch.object(phone["source"], "async_process_audio_stream", side_effect=source):
        await phone["run"](5)
        await phone["client"].close()
        await hass.async_block_till_done()
        second = await hass_ws_client(hass)
        await phone["run"](5, selected_client=second)
        different_login = await hass.auth.async_create_refresh_token(
            hass_admin_user, client_id="http://separate-test-login"
        )
        third = await hass_ws_client(hass, hass.auth.async_create_access_token(different_login))
        await phone["run"](5, selected_client=third)
    assert len(bindings) == 3
    assert bool(bindings[0] == bindings[1])
    assert bool(bindings[0] != bindings[2])
    assert not phone["backend"].active


async def close_phone_turn(hass, phone, client):
    await client.close()
    await hass.async_block_till_done()
    tasks = list(phone["runtime"].cleanup_tasks)
    if tasks:
        await asyncio.gather(*tasks)


async def test_native_resume_across_completed_sockets_needs_preview_then_separate_confirmation(
    hass, hass_ws_client, phone
):
    assert speech(await phone["run"](1)) == NOTICE
    assert speech(await phone["run"](2)).startswith(INTRO)
    assert INTRO not in speech(await phone["run"](3))
    await phone["run"](4)
    await close_phone_turn(hass, phone, phone["client"])
    second = await hass_ws_client(hass)
    reply = speech(await phone["run"](18, selected_client=second))
    assert "Welcome back! You've completed 1 of 2 voice samples" in reply
    assert "Cancel voice learning" in reply
    assert NOTICE not in reply and INTRO not in reply
    assert not phone["backend"].active
    assert not [call for call in phone["backend"].calls if call[0] == "resume"]
    await close_phone_turn(hass, phone, second)
    third = await hass_ws_client(hass)
    reply = speech(await phone["run"](18, selected_client=third))
    assert "Sample 2 of 2" in reply and INTRO not in reply
    assert phone["backend"].active and phone["backend"].count == 1
    assert len([call for call in phone["backend"].calls if call[0] == "sample"]) == 1
    assert len([call for call in phone["backend"].calls if call[0] == "resume"]) == 1
    await close_phone_turn(hass, phone, third)
    fourth = await hass_ws_client(hass)
    assert "complete" in speech(await phone["run"](3, selected_client=fourth))
    assert phone["backend"].count == 2


async def test_native_resume_cancel_before_confirmation_never_begins_or_uploads(phone):
    for marker in (1, 2, 3, 4):
        await phone["run"](marker)
    assert "Welcome back" in speech(await phone["run"](18))
    assert "deleted" in speech(await phone["run"](14))
    assert not phone["backend"].active and phone["backend"].count == 0
    assert not [call for call in phone["backend"].calls if call[0] == "resume"]
    assert len([call for call in phone["backend"].calls if call[0] == "begin"]) == 1
    assert len([call for call in phone["backend"].calls if call[0] == "sample"]) == 1


@pytest.mark.parametrize("changed", ["chat", "login", "expired", "interrupted"])
async def test_native_unverified_continuity_uses_fresh_notice_not_resume(
    hass, hass_ws_client, hass_admin_user, phone, changed
):
    for marker in (1, 2, 3, 4):
        await phone["run"](marker)
    client, chat = phone["client"], "phone-chat"
    flow = next(iter(phone["runtime"].controller.flows.values()))
    if changed == "chat":
        chat = "different-chat"
    elif changed == "login":
        login = await hass.auth.async_create_refresh_token(
            hass_admin_user, client_id="http://new-resume-login"
        )
        client = await hass_ws_client(hass, hass.auth.async_create_access_token(login))
    elif changed == "expired":
        flow.expires = 0
    else:
        flow.must_reconsent = True
    reply = speech(await phone["run"](18, selected_client=client, chat=chat))
    assert NOTICE in reply and "Welcome back" not in reply
    assert not phone["backend"].active and phone["backend"].count == 1
    assert not [call for call in phone["backend"].calls if call[0] in {"resume_preview", "resume"}]
    assert NOTICE in speech(await phone["run"](18, selected_client=client, chat=chat))
    assert not phone["backend"].active


async def test_native_privacy_is_available_before_consent_and_is_not_sample_audio(phone):
    reply = speech(await phone["run"](19))
    assert PRIVACY_DETAILS in reply and reply.endswith(NOTICE)
    assert not phone["backend"].active
    assert speech(await phone["run"](2)).startswith(INTRO)
    reply = speech(await phone["run"](19))
    assert PRIVACY_DETAILS in reply and "Sample 1 of 2" in reply and INTRO not in reply
    assert phone["backend"].count == 0
    assert not [call for call in phone["backend"].calls if call[0] == "sample"]


async def test_native_resume_rechecks_login_before_mutating_resume(phone):
    for marker in (1, 2, 3, 4, 18):
        await phone["run"](marker)
    controller = phone["runtime"].controller
    original = controller.check
    checks = 0

    def revoked(frame):
        nonlocal checks
        checks += 1
        if checks == 2:
            raise ValueError("Synthetic revoked login before resume")
        return original(frame)

    with patch.object(controller, "check", side_effect=revoked):
        assert "could not be verified" in speech(await phone["run"](18))
    assert checks == 2
    assert not phone["backend"].active
    assert not [call for call in phone["backend"].calls if call[0] == "resume"]


async def test_every_turn_can_reconnect_same_login_with_fresh_permits_and_pause(
    hass, hass_ws_client, phone
):
    assert "Before we begin" in speech(await phone["run"](1))
    await close_phone_turn(hass, phone, phone["client"])
    second = await hass_ws_client(hass)
    assert "Sample 1 of 2" in speech(await phone["run"](2, selected_client=second))
    prompt_only_permit = phone["backend"].current_permit
    flow = next(iter(phone["runtime"].controller.flows.values()))
    assert flow.permit is None
    await close_phone_turn(hass, phone, second)
    third = await hass_ws_client(hass)
    assert "Sample 2 of 2" in speech(await phone["run"](3, selected_client=third))
    samples = [call for call in phone["backend"].calls if call[0] == "sample"]
    assert len(samples) == 1
    assert samples[0][2]["permit"] != prompt_only_permit
    assert phone["backend"].count == 1
    await close_phone_turn(hass, phone, third)
    fourth = await hass_ws_client(hass)
    assert "paused" in speech(await phone["run"](4, selected_client=fourth))
    assert phone["backend"].count == 1
    assert not phone["backend"].active
    paused = next(iter(phone["runtime"].controller.flows.values()))
    assert paused.phase == "paused"
    assert paused.permit is None and paused.resume_snapshot is None


async def test_no_after_notice_reconnect_cancels_without_training(hass, hass_ws_client, phone):
    await phone["run"](1)
    await close_phone_turn(hass, phone, phone["client"])
    second = await hass_ws_client(hass)
    assert "No learning started" in speech(await phone["run"](5, selected_client=second))
    assert not phone["runtime"].controller.flows
    assert not [call for call in phone["backend"].calls if call[0] in {"begin", "sample"}]


async def test_same_login_new_chat_and_expired_notice_require_fresh_consent(
    hass, hass_ws_client, phone
):
    await phone["run"](1)
    await close_phone_turn(hass, phone, phone["client"])
    second = await hass_ws_client(hass)
    assert "Before we begin" in speech(
        await phone["run"](2, selected_client=second, chat="other-chat")
    )
    next(iter(phone["runtime"].controller.flows.values())).expires = 0
    assert "Before we begin" in speech(
        await phone["run"](2, selected_client=second, chat="other-chat")
    )
    assert not phone["backend"].active


@pytest.mark.parametrize(
    "invalid", ["missing", "revoked", "expired", "system", "long_lived", "wrong_user"]
)
async def test_login_validation_fails_closed(phone, invalid):
    await phone["run"](1)
    connection = next(iter(phone["runtime"].connections.values()))[0]
    runtime = phone["runtime"]
    user = connection.user
    valid_id = connection.refresh_token_id
    if invalid == "missing":
        connection.refresh_token_id = None
        try:
            with pytest.raises(ValueError):
                runtime.authorize(connection, user.id)
        finally:
            connection.refresh_token_id = valid_id
        return
    login = (
        None
        if invalid == "revoked"
        else SimpleNamespace(
            user=user if invalid != "wrong_user" else SimpleNamespace(id="different-test-account"),
            token_type={"system": "system", "long_lived": "long_lived_access_token"}.get(
                invalid, "normal"
            ),
            expire_at=0 if invalid == "expired" else None,
        )
    )
    with (
        patch.object(runtime.hass.auth, "async_get_refresh_token", return_value=login),
        pytest.raises(ValueError),
    ):
        runtime.authorize(connection, user.id)
    assert not phone["backend"].active


async def test_login_revocation_during_source_processing_discards_recording(phone):
    runtime = phone["runtime"]
    original = runtime.hass.auth.async_get_refresh_token
    revoked = False

    def lookup(login_id):
        return None if revoked else original(login_id)

    async def source(metadata, stream):
        nonlocal revoked
        async for _ in stream:
            pass
        revoked = True
        return stt.SpeechResult("Start learning", stt.SpeechResultState.SUCCESS)

    with (
        patch.object(runtime.hass.auth, "async_get_refresh_token", side_effect=lookup),
        patch.object(phone["source"], "async_process_audio_stream", side_effect=source),
    ):
        await phone["run"](2, expect_error=True)
    assert not runtime.frames.pending
    assert not [call for call in phone["backend"].calls if call[0] in {"begin", "sample"}]


async def test_same_login_overlapping_connections_cannot_share_a_recording_scope(
    hass, hass_ws_client, phone
):
    entered, release = asyncio.Event(), asyncio.Event()

    async def source(metadata, stream):
        async for _ in stream:
            pass
        entered.set()
        await release.wait()
        return stt.SpeechResult("start", stt.SpeechResultState.SUCCESS)

    with patch.object(phone["source"], "async_process_audio_stream", side_effect=source):
        first = asyncio.create_task(phone["run"](1))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            second = await hass_ws_client(hass)
            await phone["run"](2, selected_client=second, expect_error=True)
        finally:
            release.set()
            await first
    assert not phone["backend"].active
    assert len(phone["runtime"].controller.flows) == 1


async def test_disconnect_during_a_consented_capture_requires_new_notice(
    hass, hass_ws_client, phone
):
    await phone["run"](1)
    await phone["run"](2)
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def source(metadata, stream):
        await anext(aiter(stream))
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with patch.object(phone["source"], "async_process_audio_stream", side_effect=source):
        task = asyncio.create_task(phone["run"](3, send_eof=False))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await close_phone_turn(hass, phone, phone["client"])
            await asyncio.wait_for(cancelled.wait(), 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    second = await hass_ws_client(hass)
    assert "Before we begin" in speech(await phone["run"](2, selected_client=second))
    assert phone["backend"].count == 0
    assert not phone["backend"].active
    assert not [call for call in phone["backend"].calls if call[0] == "sample"]


async def test_login_rechecked_at_agent_before_consent_is_applied(phone):
    await phone["run"](1)
    authorize = phone["runtime"].authorize
    calls = 0

    def revoke_at_agent(connection, user_id):
        nonlocal calls
        calls += 1
        if calls >= 3:  # STT admission and post-STT check succeeded; agent must still recheck.
            raise ValueError("Synthetic revoked login")
        return authorize(connection, user_id)

    with patch.object(phone["runtime"], "authorize", side_effect=revoke_at_agent):
        assert "could not be verified" in speech(await phone["run"](2))
    assert not [call for call in phone["backend"].calls if call[0] in {"begin", "sample"}]
    assert not phone["runtime"].frames.pending


async def test_new_login_cannot_inherit_notice_after_old_socket_closes(
    hass, hass_ws_client, hass_admin_user, phone
):
    await phone["run"](1)
    await close_phone_turn(hass, phone, phone["client"])
    login = await hass.auth.async_create_refresh_token(
        hass_admin_user, client_id="http://different-login"
    )
    second = await hass_ws_client(hass, hass.auth.async_create_access_token(login))
    assert "Before we begin" in speech(await phone["run"](2, selected_client=second))
    assert not phone["backend"].active
    assert len(phone["runtime"].controller.flows) == 2


async def test_login_is_rechecked_immediately_before_sample_submission(phone):
    await phone["run"](1)
    await phone["run"](2)
    controller = phone["runtime"].controller
    original = controller.check
    checks = 0

    def revoke_before_upload(frame):
        nonlocal checks
        checks += 1
        if checks >= 2:
            raise ValueError("Synthetic login revoked before upload")
        return original(frame)

    with patch.object(controller, "check", side_effect=revoke_before_upload):
        assert "could not be verified" in speech(await phone["run"](3))
    assert checks == 2
    assert not [call for call in phone["backend"].calls if call[0] == "sample"]
    assert phone["backend"].count == 0


async def test_actual_login_removal_revokes_scope_without_disabling_account(
    hass, hass_ws_client, hass_admin_user, phone
):
    login = await hass.auth.async_create_refresh_token(
        hass_admin_user, client_id="http://revoked-test-login"
    )
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(login))
    await phone["run"](1, selected_client=client)
    connection = next(
        value[0]
        for value in phone["runtime"].connections.values()
        if value[0].refresh_token_id == login.id
    )
    await close_phone_turn(hass, phone, client)
    hass.auth.async_remove_refresh_token(login)
    assert hass_admin_user.is_active
    with pytest.raises(ValueError):
        phone["runtime"].authorize(connection, hass_admin_user.id)
    other = await hass_ws_client(hass)
    assert "Before we begin" in speech(await phone["run"](2, selected_client=other))
    assert not phone["backend"].active
