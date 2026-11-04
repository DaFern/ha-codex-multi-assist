"""Prototype through native HA pipelines, not a replacement pipeline runner.

ML/audio enhancement imports are guarded test doubles and processing is disabled.
External STT and model replies are synthetic; no microphone/TTS accuracy claim.
"""

import asyncio
import json
import logging
import sys
from dataclasses import asdict
from types import ModuleType, SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from homeassistant.components import conversation, stt
from homeassistant.core import Context
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist import DOMAIN
from custom_components.codex_assist.codex_client import CodexClient, CodexTextDelta
from custom_components.codex_assist.speaker_automation import automations_for_hass
from custom_components.codex_assist.speaker_packet import encode
from custom_components.codex_assist.voice_match import runtime_for_entry
from custom_components.codex_assist.voice_match_stt import VoiceMatchSttAdapter


@pytest.fixture
async def prototype(hass, monkeypatch):
    class UnusedProcessor:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Audio enhancement is outside this transport contract")

    for name, attr in (("pymicro_vad", "MicroVad"), ("pyspeex_noise", "AudioProcessor")):
        module = ModuleType(name)
        setattr(module, attr, UnusedProcessor)
        monkeypatch.setitem(sys.modules, name, module)

    from homeassistant.components import assist_pipeline

    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "assist_pipeline", {})
    key = Fernet.generate_key().decode()
    entry = MockConfigEntry(
        domain=DOMAIN, title="Codex Assist", unique_id=DOMAIN,
        data={"access_token": "test-only", "refresh_token": "test-only", "model": "gpt-5.4"},
        options={"voice_match_pairing_key": key},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    calls = []

    async def reply(self, **kwargs):
        calls.append(kwargs)
        yield CodexTextDelta("Test reply.")

    monkeypatch.setattr(CodexClient, "stream_turn", reply)
    responses = {}

    async def process_audio(metadata, stream):
        audio = b"".join([chunk async for chunk in stream])
        return stt.SpeechResult(responses[audio[0]], stt.SpeechResultState.SUCCESS)

    source = SimpleNamespace(
        supported_languages=["en"], supported_formats=[stt.AudioFormats.WAV],
        supported_codecs=[stt.AudioCodecs.PCM], supported_bit_rates=[stt.AudioBitRates.BITRATE_16],
        supported_sample_rates=[stt.AudioSampleRates.SAMPLERATE_16000],
        supported_channels=[stt.AudioChannels.CHANNEL_MONO],
        audio_processing=stt.SpeechAudioProcessing(False, False, False),
        async_process_audio_stream=process_audio,
    )
    adapter = VoiceMatchSttAdapter(entry, source)
    adapter.hass = hass
    adapter.entity_id = "stt.voice_match_prototype"
    original_lookup = stt.async_get_speech_to_text_engine
    monkeypatch.setattr(stt, "async_get_speech_to_text_engine",
                        lambda h, entity: adapter if entity == adapter.entity_id
                        else original_lookup(h, entity))
    pipeline = assist_pipeline.Pipeline(
        id="prototype", name="Prototype", conversation_engine="conversation.codex_assist",
        conversation_language="en", language="en", stt_engine=adapter.entity_id,
        stt_language="en", tts_engine=None, tts_language=None, tts_voice=None,
        wake_word_entity=None, wake_word_id=None, prefer_local_intents=False,
    )
    monkeypatch.setattr(assist_pipeline, "async_get_pipeline", lambda *args, **kwargs: pipeline)

    async def run(marker, *, on_event=None, context=None, end_at_stt=False):
        events = []

        def event_callback(event):
            events.append(event)
            if on_event:
                on_event(event)

        async def audio():
            yield bytes([marker, 0]) * 512

        await assist_pipeline.async_pipeline_from_audio_stream(
            hass, context=context or Context(), event_callback=event_callback,
            stt_metadata=stt.SpeechMetadata(
                language="en", format=stt.AudioFormats.WAV, codec=stt.AudioCodecs.PCM,
                bit_rate=stt.AudioBitRates.BITRATE_16,
                sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
                channel=stt.AudioChannels.CHANNEL_MONO,
            ),
            stt_stream=audio(), start_stage=assist_pipeline.PipelineStage.STT,
            end_stage=(assist_pipeline.PipelineStage.STT if end_at_stt
                       else assist_pipeline.PipelineStage.INTENT),
            audio_settings=assist_pipeline.AudioSettings(is_vad_enabled=False),
        )
        return events

    return SimpleNamespace(key=key, entry=entry, adapter=adapter, source=source,
                           responses=responses, calls=calls, run=run)


def packet(key, voice="alice", text="hello", instructions="Private style preference"):
    return encode(key, text, voice=voice, revision="a" * 32 if voice else None,
                  instructions=instructions if voice else "")


def event_data(events, name):
    return next(event.data for event in events if event.type == name)


async def test_pipeline_frontend_text_is_clean_and_preferences_still_arrive(prototype, caplog):
    from custom_components.codex_assist.speaker_packet import diagnostic_tag

    caplog.set_level(logging.INFO, logger="custom_components.codex_assist")
    p = prototype
    p.responses[1] = packet(p.key)
    events = await p.run(1)
    assert not [event for event in events if event.type == "error"]
    assert event_data(events, "stt-end")["stt_output"]["text"] == "hello"
    assert event_data(events, "intent-start")["intent_input"] == "hello"
    serialized = json.dumps([asdict(event) for event in events])
    assert "[[voice-match:" not in serialized
    assert "Private style preference" not in serialized
    assert p.key not in serialized
    assert p.responses[1] not in serialized
    assert "Private style preference" in p.calls[-1]["instructions"]
    assert [item["content"] for item in p.calls[-1]["input_items"]] == ["hello"]
    assert not runtime_for_entry(p.entry).handoffs.pending
    tag = diagnostic_tag(p.responses[1])
    messages = [record.getMessage() for record in caplog.records
                if record.getMessage().startswith("Voice Match")]
    assert any(f"receive: request={tag} result=recognised instructions_present=True"
               in message for message in messages)
    assert any(f"prompt: request={tag} stage=prompt_prepared instructions_applied=True"
               in message for message in messages)
    for private in (p.key, p.responses[1], "hello", "alice", "Private style preference"):
        assert private not in "\n".join(messages)


async def test_identical_parallel_phrases_select_the_right_native_condition(hass, prototype):
    p = prototype
    for marker, name in enumerate(("alice", "bob"), 1):
        p.responses[marker] = packet(p.key, name, text="good morning", instructions=name)
    arrived = asyncio.Event()
    count = 0

    async def barrier(call):
        nonlocal count
        count += 1
        if count == 2:
            arrived.set()
        await arrived.wait()

    hass.services.async_register("test", "barrier", barrier)
    assert await async_setup_component(hass, "automation", {"automation": [{
        "id": "prototype_greeting", "alias": "Prototype greeting", "mode": "parallel",
        "triggers": [{"trigger": "codex_assist.voice_sentence",
                      "options": {"sentence": ["good morning"]}}],
        "actions": [{"action": "test.barrier"}, {"choose": [{
            "conditions": [{"condition": "codex_assist.speaker_is",
                            "options": {"voice": name}}],
            "sequence": [{"set_conversation_response": f"Hello {name}."}],
        } for name in ("alice", "bob")],
            "default": [{"set_conversation_response": "General response."}]}],
    }]})
    await hass.async_block_till_done()
    results = await asyncio.gather(p.run(1), p.run(2))
    for events, name in zip(results, ("alice", "bob"), strict=True):
        assert event_data(events, "stt-end")["stt_output"]["text"] == "good morning"
        output = event_data(events, "intent-end")["intent_output"]
        assert output["response"]["speech"]["plain"]["speech"] == f"Hello {name}."
    assert not p.calls
    assert not runtime_for_entry(p.entry).handoffs.pending
    assert not automations_for_hass(hass).active


async def test_missing_invalid_replayed_and_uncertain_metadata_do_not_borrow_person(prototype):
    p = prototype
    p.responses[1] = packet(p.key)
    await p.run(1)
    before = len(p.calls)
    # A repeated encrypted packet cannot execute a second model turn.
    events = await p.run(1)
    assert len(p.calls) == before
    output = event_data(events, "intent-end")["intent_output"]
    assert "pairing needs attention" in output["response"]["speech"]["plain"]["speech"]
    for wire in ("hello", "[[voice-match:v1:invalid]]\nhello", ""):
        p.responses[2] = wire
        events = await p.run(2)
        assert [event for event in events if event.type == "error"]
        assert len(p.calls) == before
    p.responses[3] = packet(p.key, None)
    await p.run(3)
    assert "Private style preference" not in p.calls[-1]["instructions"]
    assert not runtime_for_entry(p.entry).handoffs.pending


async def test_cancel_between_stt_and_conversation_cleans_retained_packet(prototype):
    p = prototype
    p.responses[1] = packet(p.key)
    retained = []

    def cancel_after_stt(event):
        retained.append(event)
        if event.type == "stt-end":
            asyncio.current_task().cancel()

    task = asyncio.create_task(p.run(1, on_event=cancel_after_stt))
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert not p.calls
    assert event_data(retained, "stt-end")["stt_output"]["text"] == "hello"
    assert not runtime_for_entry(p.entry).handoffs.pending


async def test_stt_only_request_owner_cleanup_and_adapter_audio_properties(prototype):
    p = prototype
    p.responses[1] = packet(p.key)
    events = await asyncio.create_task(p.run(1, end_at_stt=True))
    await asyncio.sleep(0)
    assert event_data(events, "stt-end")["stt_output"]["text"] == "hello"
    assert not p.calls and not runtime_for_entry(p.entry).handoffs.pending
    for name in ("supported_languages", "supported_formats", "supported_codecs",
                 "supported_bit_rates", "supported_sample_rates", "supported_channels",
                 "audio_processing"):
        assert getattr(p.adapter, name) == getattr(p.source, name)


async def test_native_sentence_override_cannot_claim_speaker_and_cleans_unused_handoff(
    hass, prototype,
):
    p = prototype
    p.responses[1] = packet(p.key, text="good morning")
    assert await async_setup_component(hass, "automation", {"automation": [{
        "id": "native_override", "alias": "Native override",
        "triggers": [{"trigger": "conversation", "command": "good morning"}],
        "actions": [{"choose": [{
            "conditions": [{"condition": "codex_assist.speaker_is",
                            "options": {"voice": "alice"}}],
            "sequence": [{"set_conversation_response": "Must not select this person."}],
        }], "default": [{"set_conversation_response": "Native general response."}]}],
    }]})
    await hass.async_block_till_done()
    events = await asyncio.create_task(p.run(1))
    await asyncio.sleep(0)
    output = event_data(events, "intent-end")["intent_output"]
    assert output["response"]["speech"]["plain"]["speech"] == "Native general response."
    assert not p.calls and not runtime_for_entry(p.entry).handoffs.pending
    # A JSON/text boundary drops the private association rather than guessing it.
    plain = json.loads(json.dumps(event_data(events, "stt-end")["stt_output"]["text"]))
    await conversation.async_converse(hass, plain, None, Context(),
                                     agent_id="conversation.codex_assist")
    assert "Private style preference" not in p.calls[-1]["instructions"]


async def test_adapter_rejects_disabled_or_changed_pairing_before_issuing_handoff(prototype):
    p = prototype
    entry = type("Entry", (), {})()
    entry.entry_id = "synthetic-entry"
    entry.options = {}
    calls = []

    async def source(metadata, stream):
        calls.append(True)
        entry.options = {"voice_match_pairing_key": Fernet.generate_key().decode()}
        return stt.SpeechResult(packet(p.key), stt.SpeechResultState.SUCCESS)

    adapter = VoiceMatchSttAdapter(entry, SimpleNamespace(async_process_audio_stream=source))
    result = await adapter.async_process_audio_stream(None, None)
    assert result.result == stt.SpeechResultState.ERROR and not calls
    entry.options = {"voice_match_pairing_key": p.key}
    result = await adapter.async_process_audio_stream(None, None)
    assert result.result == stt.SpeechResultState.ERROR and calls == [True]
    assert not runtime_for_entry(entry).handoffs.pending
