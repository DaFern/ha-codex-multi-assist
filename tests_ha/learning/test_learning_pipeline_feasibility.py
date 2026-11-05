"""Native phone-protocol feasibility only: no deployed STT or training adapter.

Audio/DSP and replies are synthetic. Core owns WebSocket authentication and
pipeline execution. In-memory task identity is deliberately probed, not assumed
to be a stable HA metadata contract. The trigger interception test is a blocker
to promising an unconditionally command-free learning pipeline.
"""

import asyncio
import sys
from types import ModuleType
from typing import ClassVar

import pytest
from homeassistant.components import conversation, stt
from homeassistant.helpers import chat_session, intent
from homeassistant.setup import async_setup_component

MARKER = "voice learning probe input"


@pytest.fixture
async def pipeline_components(hass, monkeypatch):
    """Prepare real components/DSP boundaries without opening a test HTTP server."""
    class UnusedProcessor:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Real DSP is outside this identity probe")

    for name, attribute in (("pymicro_vad", "MicroVad"), ("pyspeex_noise", "AudioProcessor")):
        module = ModuleType(name)
        setattr(module, attribute, UnusedProcessor)
        monkeypatch.setitem(sys.modules, name, module)

    from homeassistant.components.assist_pipeline import default_pipeline

    class SyntheticEnhancer:
        def __init__(self, *args, **kwargs):
            pass

        def enhance_chunk(self, audio, timestamp_ms):
            return default_pipeline.EnhancedAudioChunk(audio, timestamp_ms, None)

    monkeypatch.setattr(default_pipeline, "MicroVadSpeexEnhancer", SyntheticEnhancer)
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "stt", {})
    assert await async_setup_component(hass, "assist_pipeline", {})
    # Combined tests may add a Codex entry after the phone client opens. Register
    # AI Task's media-source routes first, without creating any Codex entities.
    assert await async_setup_component(hass, "ai_task", {})


@pytest.fixture
async def phone_probe(hass, hass_ws_client, pipeline_components):
    from homeassistant.components.websocket_api.connection import current_connection

    pending, received = {}, []
    gate = {"expected": 0, "arrived": 0, "waiting": asyncio.Event(), "release": asyncio.Event()}

    class ProbeStt(stt.SpeechToTextEntity):
        _attr_name = "Learning feasibility probe"
        _attr_unique_id = "learning-feasibility-probe-stt"
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
            audio = b"".join([chunk async for chunk in stream])
            task = asyncio.current_task()
            pending[task] = (audio, current_connection.get(), chat_session.current_session.get())
            task.add_done_callback(lambda owner: pending.pop(owner, None))
            if gate["expected"]:
                gate["arrived"] += 1
                gate["waiting"].set()
                if gate["arrived"] == gate["expected"]:
                    gate["release"].set()
                await gate["release"].wait()
            return stt.SpeechResult(MARKER, stt.SpeechResultState.SUCCESS)

    class ProbeAgent(conversation.ConversationEntity):
        _attr_name = "Learning feasibility probe"
        _attr_unique_id = "learning-feasibility-probe-agent"
        supported_languages: ClassVar[list[str]] = ["en"]

        async def _async_handle_message(self, user_input, chat_log):
            frame = pending.pop(asyncio.current_task(), None)
            received.append(
                {
                    "user_id": user_input.context.user_id,
                    "device_id": user_input.device_id,
                    "frame": frame[0] if frame else None,
                    "same_connection": frame is not None and frame[1] is current_connection.get(),
                    "same_chat": frame is not None
                    and frame[2] is chat_session.current_session.get(),
                }
            )
            response = intent.IntentResponse(language="en")
            response.async_set_speech("Synthetic learning response")
            return conversation.ConversationResult(
                response=response,
                conversation_id=user_input.conversation_id,
                continue_conversation=True,
            )

    engine, agent = ProbeStt(), ProbeAgent()
    await hass.data[stt.DOMAIN].async_add_entities([engine])
    await hass.data[conversation.DOMAIN].async_add_entities([agent])
    admin = await hass_ws_client(hass)
    await admin.send_json(
        {
            "id": 1,
            "type": "assist_pipeline/pipeline/create",
            "name": "Learning feasibility probe",
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
    result = await admin.receive_json()
    assert result["success"], result
    pipeline_id = result["result"]["id"]

    async def run(client, marker=1, conversation_id=None, *, end_stage="intent", message_id=10):
        request = {
            "id": message_id,
            "type": "assist_pipeline/run",
            "pipeline": pipeline_id,
            "start_stage": "stt",
            "end_stage": end_stage,
            "input": {"sample_rate": 16000},
        }
        if conversation_id is not None:
            request["conversation_id"] = conversation_id
        await client.send_json(request)
        events = []
        while True:
            message = await asyncio.wait_for(client.receive_json(), 5)
            assert message.get("success", True), message
            if "event" not in message:
                continue
            event = message["event"]
            events.append(event)
            if event["type"] == "run-start":
                handler = event["data"]["runner_data"]["stt_binary_handler_id"]
                await client.send_bytes(bytes([handler]) + bytes([marker, 0]) * 16000)
                await client.send_bytes(bytes([handler]))
            if event["type"] == "run-end":
                assert not [event for event in events if event["type"] == "error"], events
                return events

    return {
        "admin": admin,
        "run": run,
        "pending": pending,
        "received": received,
        "agent": agent,
        "pipeline_id": pipeline_id,
        "gate": gate,
    }


async def test_native_phone_pipeline_retains_actual_caller_and_exact_audio_task(
    phone_probe, hass_admin_user
):
    probe = phone_probe
    await probe["run"](probe["admin"])
    assert len(probe["received"]) == 1
    record = probe["received"][0]
    assert record["user_id"] == hass_admin_user.id
    assert record["frame"] == bytes([1, 0]) * 16000
    assert record["same_connection"]
    assert record["same_chat"]
    assert not probe["pending"]


async def test_parallel_phone_users_do_not_share_the_audio_handoff(
    hass, hass_ws_client, phone_probe
):
    clients, users = [], []
    for index in range(2):
        user = await hass.auth.async_create_user(f"Probe user {index}", group_ids=["system-users"])
        refresh = await hass.auth.async_create_refresh_token(user, client_id="http://test-client")
        clients.append(await hass_ws_client(hass, hass.auth.async_create_access_token(refresh)))
        users.append(user)
    phone_probe["gate"]["expected"] = (
        2  # Force both recordings to overlap before either agent runs.
    )
    await asyncio.gather(
        *(
            phone_probe["run"](client, index + 1, "same-client-chosen-id")
            for index, client in enumerate(clients)
        )
    )
    by_user = {record["user_id"]: record for record in phone_probe["received"]}
    for index, user in enumerate(users):
        assert by_user[user.id]["frame"] == bytes([index + 1, 0]) * 16000
        assert by_user[user.id]["same_connection"]
    assert not phone_probe["pending"]


async def test_copied_marker_cannot_steal_a_pending_recording_on_another_connection(
    hass_ws_client, phone_probe
):
    probe = phone_probe
    probe["gate"]["expected"] = 2
    donor = asyncio.create_task(probe["run"](probe["admin"], 7, "shared-probe-id"))
    await asyncio.wait_for(probe["gate"]["waiting"].wait(), 5)
    other_connection = await hass_ws_client(probe["agent"].hass)
    try:
        for message_id in (1, 2):
            await other_connection.send_json(
                {
                    "id": message_id,
                    "type": "conversation/process",
                    "text": MARKER,
                    "agent_id": probe["agent"].entity_id,
                    "conversation_id": "shared-probe-id",
                    "language": "en",
                }
            )
            assert (await other_connection.receive_json())["success"]
            assert probe["received"][-1]["frame"] is None
            assert len(probe["pending"]) == 1
    finally:
        probe["gate"]["release"].set()
        await donor
    assert probe["received"][-1]["frame"] == bytes([7, 0]) * 16000
    assert not probe["pending"]


async def test_typed_or_copied_marker_cannot_supply_a_recording(hass, phone_probe, hass_admin_user):
    from homeassistant.core import Context

    await conversation.async_converse(
        hass,
        text=MARKER,
        context=Context(user_id=hass_admin_user.id),
        conversation_id="typed-probe",
        language="en",
        agent_id=phone_probe["agent"].entity_id,
    )
    assert phone_probe["received"][-1]["frame"] is None


async def test_stt_only_pipeline_discards_unclaimed_audio_when_its_task_ends(phone_probe):
    await phone_probe["run"](phone_probe["admin"], end_stage="stt")
    await asyncio.sleep(0)
    assert not phone_probe["received"]
    assert not phone_probe["pending"]


async def test_global_sentence_trigger_can_intercept_even_a_dedicated_pipeline(hass, phone_probe):
    from homeassistant.components.conversation.agent_manager import get_agent_manager

    intercepted = []

    async def intercept(user_input, result):
        intercepted.append(True)
        return "Intercepted by a test-only sentence trigger"

    remove = get_agent_manager(hass).register_trigger(
        sentences=[MARKER], trigger_callback=intercept
    )
    try:
        await phone_probe["run"](phone_probe["admin"])
        await asyncio.sleep(0)
        assert intercepted
        assert not phone_probe["received"], "Native triggers run before the learning agent"
        assert not phone_probe["pending"], "Unclaimed audio must be discarded, never trained"
    finally:
        remove()
