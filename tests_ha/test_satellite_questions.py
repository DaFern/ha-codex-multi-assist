"""Configured HA questions capture answers without granting ordinary voice tools."""

import asyncio
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import Context

from custom_components.codex_assist import action_receipts


@pytest.fixture(autouse=True)
def optional_audio_dependencies(monkeypatch):
    """Capture is simulated; these unavailable audio DSPs must never be used."""
    import sys

    for name, attr in (("pymicro_vad", "MicroVad"), ("pyspeex_noise", "AudioProcessor")):
        if name not in sys.modules:
            module = ModuleType(name)
            setattr(module, attr, lambda *args, **kwargs: None)
            monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
async def capture(hass, monkeypatch):
    from homeassistant.components.assist_pipeline import PipelineEvent, PipelineEventType

    from custom_components.codex_assist import protected_pipeline

    question = asyncio.get_running_loop().create_future()
    state = SimpleNamespace(
        live=True, text="yes", failed=False, exception=None, before_end=None,
        events=[], runs=[], inputs=[], question=question, active_question=question,
    )

    @contextmanager
    def session(*args, **kwargs):
        yield SimpleNamespace(conversation_id="synthetic-question")

    monkeypatch.setattr(protected_pipeline.chat_session, "async_get_chat_session", session)

    def run(**kwargs):
        state.runs.append(kwargs)
        return SimpleNamespace(**kwargs)

    class Input:
        def __init__(self, **kwargs):
            self.args = kwargs
            state.inputs.append(kwargs)

        async def execute(self, *, validate):
            assert validate is True
            callback = self.args["run"].event_callback
            callback(PipelineEvent(PipelineEventType.RUN_START, {}))
            callback(PipelineEvent(PipelineEventType.STT_START, {}))
            if state.exception:
                raise state.exception
            if state.failed:
                callback(PipelineEvent(PipelineEventType.ERROR, {"code": "stt-failed"}))
            callback(PipelineEvent(PipelineEventType.STT_END, {
                "stt_output": {"text": state.text},
            }))
            # A native STT run-end must not settle the question before validation.
            callback(PipelineEvent(PipelineEventType.RUN_END))
            assert not question.done()
            if state.before_end:
                state.before_end()
            await asyncio.sleep(0)

    monkeypatch.setattr(protected_pipeline, "PipelineRun", run)
    monkeypatch.setattr(protected_pipeline, "PipelineInput", Input)

    def callback(event):
        state.events.append(event)
        active = state.active_question
        if event.type is PipelineEventType.STT_END and not active.done():
            active.set_result(event.data["stt_output"]["text"])
        elif event.type is PipelineEventType.RUN_END and not active.done():
            active.set_result(None)

    async def execute():
        await protected_pipeline.async_run_question_pipeline(
            hass, pipeline=SimpleNamespace(stt_language="en", language="en"),
            context=Context(), audio_stream=object(), event_callback=callback,
            question=question, current=lambda: state.live and state.active_question is question,
            device_id="synthetic-device", satellite_id="assist_satellite.synthetic",
        )

    state.execute = execute
    return state


@pytest.mark.parametrize("text", ["yes", "no", "turn off all lights", "a free text answer"])
async def test_only_captures_text_never_runs_intents_or_tools(capture, text):
    capture.text = text
    await capture.execute()
    assert capture.question.result() == text
    assert len(capture.runs) == 1
    assert capture.runs[0]["start_stage"].value == "stt"
    assert capture.runs[0]["end_stage"].value == "stt"
    kinds = [event.type for event in capture.events]
    assert kinds.count("stt-end") == 1
    assert kinds.count("run-end") == 1
    assert "intent-start" not in kinds
    assert "tts-start" not in kinds
    assert not action_receipts._RECEIPTS


async def test_private_transcript_carrier_is_not_returned(capture):
    class PrivateText(str):
        pass

    capture.text = PrivateText("yes")
    await capture.execute()
    assert type(capture.question.result()) is str
    assert capture.question.result() == "yes"


@pytest.mark.parametrize(
    "answer,expected", [("yes", "yes"), ("no", "no"), ("something else", None)],
)
async def test_native_ha_still_matches_configured_answers(hass, capture, answer, expected):
    from homeassistant.components.assist_satellite.entity import AssistSatelliteEntity

    capture.text = answer
    await capture.execute()
    result = AssistSatelliteEntity._question_response_to_answer(
        SimpleNamespace(hass=hass), capture.question.result(),
        [{"id": "yes", "sentences": ["yes"]}, {"id": "no", "sentences": ["no"]}],
    )
    assert result.id == expected


@pytest.mark.parametrize("text", [None, "", "x" * 8193], ids=["none", "empty", "oversized"])
async def test_empty_or_oversized_answer_is_not_a_command(capture, text):
    capture.text = text
    await capture.execute()
    assert capture.question.result() is None
    assert not any(e.type == "stt-end" for e in capture.events)


@pytest.mark.parametrize("failure", ["stt", "exception", "timeout", "cancel"])
async def test_failed_capture_settles_original_future_without_answer(capture, failure):
    if failure == "stt":
        capture.failed = True
    else:
        capture.exception = {
            "exception": RuntimeError("synthetic failure"),
            "timeout": TimeoutError(),
            "cancel": asyncio.CancelledError(),
        }[failure]
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await capture.execute()
    else:
        await capture.execute()
    assert capture.question.result() is None
    assert not any(e.type == "stt-end" for e in capture.events)


async def test_connection_loss_during_stt_drops_buffered_answer(capture):
    capture.before_end = lambda: setattr(capture, "live", False)
    await capture.execute()
    assert capture.question.result() is None
    assert not any(e.type == "stt-end" for e in capture.events)
    assert not any(e.type == "run-end" for e in capture.events)


async def test_replaced_question_is_not_completed(capture):
    replacement = asyncio.get_running_loop().create_future()
    capture.before_end = lambda: setattr(capture, "active_question", replacement)
    await capture.execute()
    assert capture.question.result() is None
    assert not replacement.done()
    replacement.cancel()


async def test_finished_question_never_starts_another_capture(capture):
    capture.question.set_result("existing")
    await capture.execute()
    assert capture.question.result() == "existing"
    assert capture.runs == []


@pytest.fixture
def adapter_module(monkeypatch):
    import sys

    for name, attr in (("pymicro_vad", "MicroVad"), ("pyspeex_noise", "AudioProcessor")):
        if name not in sys.modules:
            module = ModuleType(name)
            setattr(module, attr, lambda *args, **kwargs: None)
            monkeypatch.setitem(sys.modules, name, module)
    from custom_components.codex_assist import kiosk_adapter

    return kiosk_adapter


async def test_native_question_routes_to_capture_not_protected_model(adapter_module, monkeypatch):
    module = adapter_module
    adapter = object.__new__(module.KioskSatelliteAdapter)
    adapter._tasks = {}
    adapter._answer_question = AsyncMock()
    protected = AsyncMock(side_effect=AssertionError("Question ran ordinary protected tools"))
    monkeypatch.setattr(module, "async_run_protected_pipeline", protected)
    satellite = SimpleNamespace(_ask_question_future=asyncio.get_running_loop().create_future())
    await adapter._accept(
        satellite, object(),
        adapter_module.PipelineStage.STT, adapter_module.PipelineStage.TTS, None, None,
    )
    adapter._answer_question.assert_awaited_once()
    protected.assert_not_awaited()
    assert adapter._tasks == {}
    satellite._ask_question_future.cancel()


@pytest.fixture
async def pinned_adapter(hass, adapter_module, monkeypatch):
    module = adapter_module
    adapter = object.__new__(module.KioskSatelliteAdapter)
    entry = SimpleNamespace(
        entry_id="synthetic-codex", options={"question_stt_engine": "stt.question"},
    )
    question = asyncio.get_running_loop().create_future()
    satellite = SimpleNamespace(
        entity_id="assist_satellite.synthetic", _ask_question_future=question,
        _wake_word_intercept_future=None, tts_options=None,
        _resolve_pipeline=lambda: "synthetic-pipeline", _resolve_vad_sensitivity=lambda: 0.7,
        _internal_on_pipeline_event=Mock(),
    )
    identity = SimpleNamespace(device_id="synthetic-device")
    source = SimpleNamespace(
        platform="codex_assist", config_entry_id=entry.entry_id, disabled_by=None,
    )
    from homeassistant.components.assist_pipeline import Pipeline

    pipeline = Pipeline(
        id="synthetic-pipeline", name="Synthetic", stt_engine="stt.synthetic",
        stt_language="en", language="en", conversation_engine="conversation.synthetic",
        conversation_language="en", tts_engine=None, tts_language=None, tts_voice=None,
        wake_word_entity=None, wake_word_id=None,
    )
    question_identity = SimpleNamespace(config_entry_id="synthetic-whisper")
    question_entry = SimpleNamespace(disabled_by=None)
    question_source = SimpleNamespace(supported_languages=["en"])
    registry = SimpleNamespace(async_get=lambda eid: {
        satellite.entity_id: identity, pipeline.stt_engine: source,
        "stt.question": question_identity,
    }.get(eid))
    class Agent:
        pass

    agent = Agent()
    agent.entry = entry
    adapter.hass, adapter.entry = hass, entry
    adapter._closed, adapter._options = False, entry.options
    adapter._tasks, adapter._agent_type = {}, Agent
    adapter._bindings = {satellite.entity_id: (object(), object())}
    adapter._connection_checks = {satellite.entity_id: lambda connection: True}
    adapter._enrollments = {satellite.entity_id: ("synthetic",)}
    adapter._registry_identity = lambda identity: ("synthetic",)
    adapter._entity = lambda eid: satellite
    adapter._binding, adapter._drop_conversation = Mock(), Mock()
    monkeypatch.setattr(module.er, "async_get", lambda hass: registry)
    monkeypatch.setattr(module, "async_get_pipeline", lambda hass, id: pipeline)
    monkeypatch.setattr(module.conversation, "async_get_agent", lambda hass, id: agent)
    monkeypatch.setattr(
        hass.config_entries, "async_get_entry", lambda eid: question_entry,
    )
    monkeypatch.setattr(module, "question_stt_source", lambda hass, eid: question_source)
    return SimpleNamespace(
        adapter=adapter, satellite=satellite, question=question, entry=entry, source=source,
        module=module, question_source=question_source, question_entry=question_entry,
    )


@pytest.mark.parametrize("change", [
    "none", "options", "future", "closed", "source", "connection",
    "question_source", "question_entry", "language",
])
async def test_capture_pins_question_and_transport_but_never_checks_speaker(
    pinned_adapter, monkeypatch, change,
):
    p = pinned_adapter

    async def capture(*args, **kwargs):
        assert kwargs["current"]()
        assert kwargs["pipeline"].stt_engine == "stt.question"
        if change == "options":
            p.entry.options = {}
        elif change == "future":
            p.satellite._ask_question_future = asyncio.get_running_loop().create_future()
        elif change == "closed":
            p.adapter._closed = True
        elif change == "source":
            p.source.disabled_by = "user"
        elif change == "connection":
            p.adapter._connection_checks[p.satellite.entity_id] = lambda connection: False
        elif change == "question_source":
            monkeypatch.setattr(p.module, "question_stt_source", lambda *args: object())
        elif change == "question_entry":
            p.question_entry.disabled_by = "user"
        elif change == "language":
            p.question_source.supported_languages = []
        assert kwargs["current"]() is (change == "none")

    runner = AsyncMock(side_effect=capture)
    monkeypatch.setattr(p.module, "async_run_question_pipeline", runner)
    await p.adapter._answer_question(
        p.satellite, p.question, object(),
        p.module.PipelineStage.STT, p.module.PipelineStage.TTS, None, None,
    )
    runner.assert_awaited_once()
    p.adapter._binding.assert_called_once_with(p.satellite)
    p.question.cancel()
    p.satellite._ask_question_future.cancel()


@pytest.mark.parametrize("invalid", [None, "", "stt.filtered", "stt.missing"])
async def test_missing_question_engine_never_falls_back(pinned_adapter, monkeypatch, invalid):
    p = pinned_adapter
    p.entry.options["question_stt_engine"] = invalid
    def unavailable(*args):
        raise ValueError("Unavailable")
    monkeypatch.setattr(p.module, "question_stt_source", unavailable)
    runner = AsyncMock()
    monkeypatch.setattr(p.module, "async_run_question_pipeline", runner)
    with pytest.raises(ValueError):
        await p.adapter._answer_question(
            p.satellite, p.question, object(), p.module.PipelineStage.STT,
            p.module.PipelineStage.TTS, None, None,
        )
    runner.assert_not_awaited()
    p.question.cancel()


@pytest.mark.parametrize("change", [
    "none", "missing", "disabled", "wrong_platform", "unavailable", "filtered", "unknown",
])
async def test_question_source_requires_ordinary_whisper(hass, monkeypatch, change):
    from custom_components.codex_assist import protected_pipeline as module

    registered = SimpleNamespace(platform="wyoming", disabled_by=None)
    program = SimpleNamespace(name="faster-whisper")
    source = SimpleNamespace(
        available=True, platform=SimpleNamespace(platform_name="wyoming"),
        service=SimpleNamespace(info=SimpleNamespace(asr=[program])),
    )
    if change == "missing":
        registered = None
    elif change == "disabled":
        registered.disabled_by = "user"
    elif change == "wrong_platform":
        registered.platform = "codex_assist"
    elif change == "unavailable":
        source.available = False
    elif change == "filtered":
        program.name = "voice-match-personal"
    elif change == "unknown":
        program.name = "unknown-proxy"
    monkeypatch.setattr(module.er, "async_get", lambda hass: SimpleNamespace(
        async_get=lambda eid: registered,
    ))
    monkeypatch.setattr(module.stt, "async_get_speech_to_text_entity", lambda *args: source)
    if change == "none":
        assert module.question_stt_source(hass, "stt.question") is source
    else:
        with pytest.raises(ValueError):
            module.question_stt_source(hass, "stt.question")


@pytest.mark.parametrize("selection", ["stt.question", "", "stt.filtered"])
async def test_question_options_preserve_unrelated_settings(hass, monkeypatch, selection):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.codex_assist import config_flow, protected_pipeline

    entry = MockConfigEntry(domain="codex_assist", options={
        "guest_voice_role_id": "existing-role", "question_stt_engine": "stt.old",
    })
    entry.add_to_hass(hass)
    flow = config_flow.CodexAssistOptionsFlow()
    flow.hass = hass
    flow.handler = entry.entry_id
    monkeypatch.setattr(config_flow, "satellite_tools_supported", lambda: True)
    def resolve(hass, eid):
        if eid == "stt.filtered":
            raise ValueError("Filtered engine")
        return object()
    monkeypatch.setattr(protected_pipeline, "question_stt_source", resolve)
    result = await flow.async_step_questions({"question_stt_engine": selection})
    if selection == "stt.filtered":
        assert result["errors"] == {"base": "invalid_question_stt"}
        assert entry.options["question_stt_engine"] == "stt.old"
    else:
        assert result["data"]["guest_voice_role_id"] == "existing-role"
        if selection:
            assert result["data"]["question_stt_engine"] == selection
        else:
            assert "question_stt_engine" not in result["data"]
