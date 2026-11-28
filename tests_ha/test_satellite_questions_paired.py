"""Paired real-HA/ESPHome question lifecycle; external audio/network are simulated."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("test_satellite_admission")


@pytest.fixture
def question_voice(native_esphome_voice, monkeypatch):
    """A distinct plain-text source; the filtered source must never receive answers."""
    from homeassistant.components import stt
    from homeassistant.helpers import entity_registry as er
    from testsupport.ha_test import MockConfigEntry

    h = native_esphome_voice
    hass = h.adapter.hass
    entry = MockConfigEntry(domain="wyoming")
    entry.add_to_hass(hass)
    identity = er.async_get(hass).async_get_or_create(
        "stt", "wyoming", "synthetic-question-whisper", config_entry=entry,
    )
    hass.config_entries.async_update_entry(
        h.n.entry, options={**h.n.entry.options, "question_stt_engine": identity.entity_id},
    )
    h.adapter._options = h.n.entry.options
    filtered_lookup = stt.async_get_speech_to_text_engine
    calls = []

    async def transcribe(metadata, stream):
        calls.append(b"".join([part async for part in stream]))
        return stt.SpeechResult(h.n.state.text, stt.SpeechResultState.SUCCESS)

    source = SimpleNamespace(
        entity_id=identity.entity_id, available=True,
        platform=SimpleNamespace(platform_name="wyoming"),
        service=SimpleNamespace(info=SimpleNamespace(asr=[SimpleNamespace(name="faster-whisper")])),
        supported_languages=["en"], check_metadata=lambda metadata: True,
        audio_processing=stt.SpeechAudioProcessing(False, False, False),
        async_process_audio_stream=transcribe,
    )
    monkeypatch.setattr(stt, "async_get_speech_to_text_entity", lambda hass, eid: (
        source if eid == identity.entity_id else None
    ))
    monkeypatch.setattr(stt, "async_get_speech_to_text_engine", lambda hass, eid: (
        source if eid == identity.entity_id else filtered_lookup(hass, eid)
    ))
    h.question_calls = calls
    return h


@pytest.mark.parametrize("speaker", [None, "child", "owner"])
@pytest.mark.parametrize("answer,expected", [
    ("yes", "yes"), ("no", "no"), ("turn off the lights", None),
])
async def test_native_question_accepts_any_speaker_without_normal_tools(
    question_voice, monkeypatch, speaker, answer, expected,
):
    h = question_voice
    h.n.state.speaker, h.n.state.text = speaker, answer
    protected = AsyncMock(side_effect=AssertionError("Question entered protected tool dispatch"))
    monkeypatch.setattr(h.adapter.ingress, "async_voice_turn", protected)
    monkeypatch.setattr(
        h.satellite, "_resolve_announcement_media_id",
        AsyncMock(return_value=SimpleNamespace(message="Synthetic configured question")),
    )

    async def start_question(announcement):
        await h.run()

    monkeypatch.setattr(h.satellite, "async_start_conversation", start_question)
    result = await h.satellite.async_internal_ask_question(
        question="Synthetic configured question", preannounce=False,
        answers=[{"id": "yes", "sentences": ["yes"]}, {"id": "no", "sentences": ["no"]}],
    )
    assert result.id == expected and result.sentence == answer
    assert type(result.sentence) is str
    assert h.satellite._ask_question_future is None
    assert h.n.state.model_calls == [] and h.n.env.calls == [] and h.n.state.tts == []
    protected.assert_not_awaited()
    assert not h.adapter.ingress._pending and not h.adapter.ingress._active
    assert not any(e.type in {"intent-start", "tts-start"} for e in h.events)
    assert len(h.question_calls) == 1
    assert h.n.state.last_wire is None


async def test_question_engine_is_never_used_for_ordinary_commands(question_voice):
    h = question_voice
    await h.run()
    assert h.question_calls == []
    assert h.n.state.last_wire is not None


@pytest.mark.parametrize("change", ["plaintext", "disconnected", "replaced_connection"])
async def test_question_retains_native_transport_checks(
    native_esphome_voice, change,
):
    h = native_esphome_voice
    question = asyncio.get_running_loop().create_future()
    h.satellite._ask_question_future = question
    h.n.state.text = "yes"
    h.adapter._binding(h.satellite)
    if change == "plaintext":
        h.client.clear_noise_psk()
    elif change == "disconnected":
        h.runtime.async_on_disconnect()
    else:
        h.client._connection = h.connection(ready=False)
    await h.run()
    assert question.done() and question.result() is None
    assert h.n.state.model_calls == [] and h.n.env.calls == []
    h.satellite._ask_question_future = None
