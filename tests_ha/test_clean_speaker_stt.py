"""Prototype through native HA pipelines, not a replacement pipeline runner.

ML/audio enhancement imports are guarded test doubles and processing is disabled.
External STT and model replies are synthetic; no microphone/TTS accuracy claim.
"""

import asyncio
import json
import logging
import sys
from dataclasses import asdict, replace
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
from custom_components.codex_assist.voice_match import (
    CONF_CLEAN_TRANSCRIPT,
    CONF_PERSONAL_STT_SOURCE,
    runtime_for_entry,
)
from custom_components.codex_assist.voice_match_stt import VoiceMatchSttAdapter


@pytest.fixture
async def prototype(hass, hass_admin_user, monkeypatch):
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
            hass, context=context or Context(user_id=hass_admin_user.id),
            event_callback=event_callback,
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

    def make_packet(voice="alice", text="hello", instructions="Private style preference",
                    speaker_name=None):
        return packet(key, voice, text, instructions, speaker_name,
                      ha_user_id=hass_admin_user.id if voice else None)

    return SimpleNamespace(key=key, user_id=hass_admin_user.id, packet=make_packet,
                           entry=entry, adapter=adapter, source=source, responses=responses,
                           calls=calls, run=run, pipeline=pipeline)


@pytest.fixture
async def managed(prototype, hass, monkeypatch):
    """Real setup/options-reload/registry; external Wyoming lookup remains synthetic."""
    from homeassistant.components import assist_pipeline
    from homeassistant.helpers import entity_registry as er

    from custom_components.codex_assist.entry_modules import learning_supported

    if not learning_supported():
        pytest.skip("Managed clean voice messages require HA 2026.10+")
    p = prototype
    source_id = "stt.synthetic_personal"
    monkeypatch.setattr(
        "custom_components.codex_assist.voice_match_stt.resolve_personal_source",
        lambda _hass, entity: p.source if entity == source_id else None,
    )
    hass.config_entries.async_update_entry(p.entry, options={
        **p.entry.options, CONF_CLEAN_TRANSCRIPT: True, CONF_PERSONAL_STT_SOURCE: source_id,
    })
    await hass.async_block_till_done()
    registered = [item for item in er.async_entries_for_config_entry(
        er.async_get(hass), p.entry.entry_id,
    ) if item.domain == "stt"]
    assert len(registered) == 1
    p.adapter = stt.async_get_speech_to_text_entity(hass, registered[0].entity_id)
    assert isinstance(p.adapter, VoiceMatchSttAdapter) and p.adapter.available
    pipeline = replace(p.pipeline, stt_engine=p.adapter.entity_id)
    monkeypatch.setattr(assist_pipeline, "async_get_pipeline", lambda *args, **kwargs: pipeline)
    return p


def packet(key, voice="alice", text="hello", instructions="Private style preference",
           speaker_name=None, *, ha_user_id=None):
    return encode(key, text, voice=voice, revision="a" * 32 if voice else None,
                  instructions=instructions if voice else "", speaker_name=speaker_name,
                  ha_user_id=ha_user_id)


def event_data(events, name):
    return next(event.data for event in events if event.type == name)


@pytest.mark.parametrize("instructions", ["Private style preference", ""])
async def test_pipeline_frontend_text_is_clean_and_preferences_still_arrive(
    prototype, caplog, instructions,
):
    from custom_components.codex_assist.speaker_packet import diagnostic_tag

    caplog.set_level(logging.INFO, logger="custom_components.codex_assist")
    p = prototype
    p.responses[1] = p.packet(instructions=instructions, speaker_name="Alice")
    events = await p.run(1)
    assert not [event for event in events if event.type == "error"]
    assert event_data(events, "stt-end")["stt_output"]["text"] == "hello"
    assert event_data(events, "intent-start")["intent_input"] == "hello"
    serialized = json.dumps([asdict(event) for event in events])
    assert "[[voice-match:" not in serialized
    assert "Private style preference" not in serialized
    assert "Alice" not in serialized
    assert p.key not in serialized
    assert p.responses[1] not in serialized
    assert '"Alice"' in p.calls[-1]["instructions"]
    if instructions:
        assert instructions in p.calls[-1]["instructions"]
    assert "say you recognise their voice" in p.calls[-1]["instructions"]
    assert [item["content"] for item in p.calls[-1]["input_items"]] == ["hello"]
    assert not runtime_for_entry(p.entry).handoffs.pending
    tag = diagnostic_tag(p.responses[1])
    messages = [record.getMessage() for record in caplog.records
                if record.getMessage().startswith("Voice Match")]
    assert any(f"receive: request={tag} result=recognised binding=matched "
               f"instructions_present={bool(instructions)}"
               in message for message in messages)
    assert any((f"prompt: request={tag} stage=prompt_prepared "
                f"instructions_applied={bool(instructions)}")
               in message for message in messages)
    for private in (p.key, p.responses[1], "hello", "alice", "Alice", "Private style preference"):
        assert private not in "\n".join(messages)


async def test_identical_parallel_phrases_select_the_right_native_condition(hass, prototype):
    p = prototype
    for marker, name in enumerate(("alice", "bob"), 1):
        p.responses[marker] = p.packet(name, text="good morning", instructions=name)
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
    p.responses[1] = p.packet()
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
    p.responses[3] = p.packet(None)
    await p.run(3)
    assert "Private style preference" not in p.calls[-1]["instructions"]
    assert not runtime_for_entry(p.entry).handoffs.pending


async def test_cancel_between_stt_and_conversation_cleans_retained_packet(prototype):
    p = prototype
    p.responses[1] = p.packet()
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
    p.responses[1] = p.packet()
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
    p.responses[1] = p.packet(text="good morning")
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
        return stt.SpeechResult(p.packet(), stt.SpeechResultState.SUCCESS)

    adapter = VoiceMatchSttAdapter(entry, SimpleNamespace(async_process_audio_stream=source))
    result = await adapter.async_process_audio_stream(None, None)
    assert result.result == stt.SpeechResultState.ERROR and not calls
    entry.options = {"voice_match_pairing_key": p.key}
    result = await adapter.async_process_audio_stream(None, None)
    assert result.result == stt.SpeechResultState.ERROR and calls == [True]
    assert not runtime_for_entry(entry).handoffs.pending


async def test_clean_entity_is_default_off(prototype, hass):
    from homeassistant.helpers import entity_registry as er

    assert not [item for item in er.async_entries_for_config_entry(
        er.async_get(hass), prototype.entry.entry_id,
    ) if item.domain == "stt"]
    assert not prototype.entry.options.get(CONF_CLEAN_TRANSCRIPT)


async def test_managed_native_pipeline_is_clean_and_name_reaches_model(managed):
    p = managed
    p.responses[1] = p.packet(instructions="", speaker_name="Alice")
    events = await asyncio.create_task(p.run(1))
    await asyncio.sleep(0)
    assert not [event for event in events if event.type == "error"]
    assert event_data(events, "stt-end")["stt_output"]["text"] == "hello"
    serialized = json.dumps([asdict(event) for event in events])
    assert "[[voice-match:" not in serialized and "Alice" not in serialized
    assert '"Alice"' in p.calls[-1]["instructions"]
    runtime = runtime_for_entry(p.entry)
    assert not runtime.handoffs.pending and not runtime.clean_tasks


@pytest.mark.parametrize("phase", ["recording", "handoff", "model"])
async def test_managed_unload_cancels_request_and_clears_private_state(
    managed, hass, monkeypatch, phase,
):
    p = managed
    reached = asyncio.Event()
    blocker = asyncio.Event()
    retained = []
    p.responses[1] = p.packet()

    if phase == "recording":
        async def source(metadata, stream):
            reached.set()
            await blocker.wait()
        p.source.async_process_audio_stream = source
    elif phase == "model":
        async def reply(self, **kwargs):
            reached.set()
            await blocker.wait()
            yield CodexTextDelta("Must not finish.")
        monkeypatch.setattr(CodexClient, "stream_turn", reply)
    else:
        original_converse = conversation.async_converse

        async def delayed_converse(*args, **kwargs):
            reached.set()
            await blocker.wait()
            return await original_converse(*args, **kwargs)

        monkeypatch.setattr(conversation, "async_converse", delayed_converse)

    def event_callback(event):
        retained.append(event)

    task = asyncio.create_task(p.run(1, on_event=event_callback))
    await reached.wait()
    assert await hass.config_entries.async_unload(p.entry.entry_id)
    with pytest.raises(asyncio.CancelledError):
        await task
    runtime = runtime_for_entry(p.entry)
    assert not runtime.handoffs.pending and not runtime.clean_tasks
    assert not p.adapter.available
    assert "[[voice-match:" not in json.dumps([asdict(event) for event in retained])
    assert not p.calls


@pytest.mark.parametrize("change", ["disable", "key", "source"])
async def test_managed_midrecord_settings_change_discards_result(managed, hass, change):
    p = managed
    wire = p.packet()

    async def source(metadata, stream):
        options = dict(p.entry.options)
        if change == "disable":
            options[CONF_CLEAN_TRANSCRIPT] = False
        elif change == "key":
            options["voice_match_pairing_key"] = Fernet.generate_key().decode()
        else:
            options[CONF_PERSONAL_STT_SOURCE] = "stt.other"
        # The listener's scheduled reload has not run before the synchronous guard.
        hass.config_entries.async_update_entry(p.entry, options=options)
        return stt.SpeechResult(wire, stt.SpeechResultState.SUCCESS)

    p.source.async_process_audio_stream = source
    task = asyncio.create_task(p.adapter.async_process_audio_stream(None, None))
    try:
        result = await task
    except asyncio.CancelledError:
        # HA's eager reload may cancel the request before the post-STT guard.
        assert task.cancelled()
    else:
        assert result.result == stt.SpeechResultState.ERROR and result.text is None
    await hass.async_block_till_done()
    assert not runtime_for_entry(p.entry).handoffs.pending and not p.calls


@pytest.mark.parametrize("outcome", ["missing", "exception", "private_error", "plain"])
async def test_managed_source_failures_never_publish_header_or_retry(managed, monkeypatch, outcome):
    p = managed
    calls = []

    async def source(metadata, stream):
        calls.append(True)
        if outcome == "exception":
            raise RuntimeError("private peer failure")
        return stt.SpeechResult(
            "hello" if outcome == "plain" else p.packet(),
            (stt.SpeechResultState.ERROR if outcome == "private_error"
             else stt.SpeechResultState.SUCCESS),
        )

    p.source.async_process_audio_stream = source
    if outcome == "missing":
        monkeypatch.setattr(
            "custom_components.codex_assist.voice_match_stt.resolve_personal_source",
            lambda *args: None,
        )
        assert not p.adapter.available
    result = await p.adapter.async_process_audio_stream(None, None)
    assert result.result == stt.SpeechResultState.ERROR and result.text is None
    assert len(calls) == (0 if outcome == "missing" else 1)
    assert not runtime_for_entry(p.entry).handoffs.pending and not p.calls


async def test_disable_reload_removes_entity_and_keeps_replay_cache(managed, hass):
    p = managed
    p.responses[1] = p.packet()
    await asyncio.create_task(p.run(1))
    runtime = runtime_for_entry(p.entry)
    seen = dict(runtime.seen)
    assert seen
    old = p.adapter
    hass.config_entries.async_update_entry(p.entry, options={"voice_match_pairing_key": p.key})
    await hass.async_block_till_done()
    assert stt.async_get_speech_to_text_entity(hass, old.entity_id) is None
    assert not old.available and dict(runtime.seen) == seen
    assert hass.states.get("conversation.codex_assist") is not None
    assert not runtime.handoffs.pending and not runtime.clean_tasks
    hass.config_entries.async_update_entry(p.entry, options={
        "voice_match_pairing_key": p.key,
        CONF_CLEAN_TRANSCRIPT: True, CONF_PERSONAL_STT_SOURCE: "stt.synthetic_personal",
    })
    await hass.async_block_till_done()
    new = stt.async_get_speech_to_text_entity(hass, old.entity_id)
    assert new is not old and new.unique_id == old.unique_id and new.available
    assert dict(runtime.seen) == seen
    before = len(p.calls)
    await asyncio.create_task(p.run(1))
    assert len(p.calls) == before  # Re-enable does not revive an already used packet.


async def test_missing_source_only_disables_clean_entity_then_recovers(managed, hass, monkeypatch):
    p = managed
    source_id = p.entry.options[CONF_PERSONAL_STT_SOURCE]
    present = [False]
    monkeypatch.setattr(
        "custom_components.codex_assist.voice_match_stt.resolve_personal_source",
        lambda _hass, entity: p.source if present[0] and entity == source_id else None,
    )
    assert await hass.config_entries.async_reload(p.entry.entry_id)
    await hass.async_block_till_done()
    adapter = stt.async_get_speech_to_text_entity(hass, p.adapter.entity_id)
    assert adapter is not None and not adapter.available
    assert hass.states.get("conversation.codex_assist").state != "unavailable"
    assert hass.states.get("ai_task.codex_assist_ai_task").state != "unavailable"
    present[0] = True
    hass.states.async_set(source_id, "ready")
    await hass.async_block_till_done()
    assert adapter.available
    assert hass.states.get(adapter.entity_id).state != "unavailable"
    p.responses[1] = p.packet()
    events = await asyncio.create_task(p.run(1))
    assert not [event for event in events if event.type == "error"]


async def test_managed_simultaneous_identical_words_keep_their_own_names(managed):
    p = managed
    p.responses[1] = p.packet(speaker_name="Alice")
    p.responses[2] = p.packet(voice="bob", speaker_name="Bob")
    events = await asyncio.gather(p.run(1), p.run(2))
    assert all(event_data(items, "stt-end")["stt_output"]["text"] == "hello" for items in events)
    prompts = [call["instructions"] for call in p.calls]
    assert len(prompts) == 2
    assert sum('"Alice"' in prompt and '"Bob"' not in prompt for prompt in prompts) == 1
    assert sum('"Bob"' in prompt and '"Alice"' not in prompt for prompt in prompts) == 1
