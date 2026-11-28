"""STT-only -> admitted fixed tools -> TTS-only, on one owning pipeline task.

This runner never invokes the native intent stage, a conversation agent, sentence
triggers, general Assist discovery, prompt templates or conversation history.
The embedding experimental ESPHome adapter owns connection authentication.
"""

import asyncio
import time

from homeassistant.components import stt
from homeassistant.components.assist_pipeline import (
    AudioSettings,
    PipelineEvent,
    PipelineEventType,
    PipelineInput,
    PipelineRun,
    PipelineStage,
)
from homeassistant.helpers import chat_session
from homeassistant.helpers import entity_registry as er

DENIAL_SPEECH = "This voice request is not authorised."
FAILURE_SPEECH = "I couldn't confirm that request."
CONF_QUESTION_STT = "question_stt_engine"


def question_stt_source(hass, entity_id):
    """Resolve an explicitly selected ordinary Whisper provider, never Voice Match."""
    if not isinstance(entity_id, str) or not entity_id.startswith("stt."):
        raise ValueError("Select an ordinary Wyoming Whisper question engine")
    registered = er.async_get(hass).async_get(entity_id)
    source = stt.async_get_speech_to_text_entity(hass, entity_id)
    if (
        registered is None or registered.platform != "wyoming"
        or registered.disabled_by is not None or source is None or not source.available
        or source.platform is None or source.platform.platform_name != "wyoming"
    ):
        raise ValueError("Question Whisper engine is unavailable")
    programs = getattr(getattr(getattr(source, "service", None), "info", None), "asr", None)
    if not programs or any(
        program.name not in {"faster-whisper", "whisper"} for program in programs
    ):
        raise ValueError("Question engine must be ordinary Whisper, not a voice filter")
    return source


async def async_run_question_pipeline(
    hass, *, pipeline, context, audio_stream, event_callback, question, current,
    device_id, satellite_id, tts_audio_output=None, wake_word_phrase=None,
    silence_seconds=0.7,
):
    """Capture a configured HA question's reply; never dispatch an ordinary request.

    The question and its consequences belong to the calling HA automation. The
    answer does not require speaker/role authorisation. The caller still pins the
    actual satellite connection and exact native future across audio awaits.
    Buffer STT_END so a replaced/closed question cannot receive captured text.
    """
    text = None
    stt_event = None
    failed = False

    def events(event):
        nonlocal text, stt_event, failed
        if event.type is PipelineEventType.STT_END:
            text = (event.data or {}).get("stt_output", {}).get("text")
            stt_event = event
            return
        if event.type is PipelineEventType.RUN_END:
            return
        if event.type is PipelineEventType.ERROR:
            failed = True
        if current() and not question.done():
            event_callback(event)

    try:
        if not current() or question.done():
            return
        async with asyncio.timeout(30):
            with chat_session.async_get_chat_session(hass) as session:
                run = PipelineRun(
                    hass=hass, context=context, pipeline=pipeline,
                    event_callback=events, tts_audio_output=tts_audio_output,
                    start_stage=PipelineStage.STT, end_stage=PipelineStage.STT,
                    audio_settings=AudioSettings(silence_seconds=silence_seconds),
                )
                await PipelineInput(
                    run=run, session=session, stt_metadata=stt.SpeechMetadata(
                        language=pipeline.stt_language or pipeline.language,
                        format=stt.AudioFormats.WAV, codec=stt.AudioCodecs.PCM,
                        bit_rate=stt.AudioBitRates.BITRATE_16,
                        sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
                        channel=stt.AudioChannels.CHANNEL_MONO,
                    ),
                    stt_stream=audio_stream, wake_word_phrase=wake_word_phrase,
                    device_id=device_id, satellite_id=satellite_id,
                ).execute(validate=True)
                if (
                    not failed and isinstance(text, str) and 0 < len(text) <= 8192
                    and stt_event is not None and current() and not question.done()
                ):
                    # Strip the private STT carrier's object identity. Native HA
                    # owns answer matching; no voice packet, model or tools run.
                    data = dict(stt_event.data)
                    data["stt_output"] = {**data["stt_output"], "text": str(text)}
                    event_callback(PipelineEvent(PipelineEventType.STT_END, data))
    except asyncio.CancelledError:
        raise
    except Exception:
        if current() and not question.done():
            event_callback(PipelineEvent(PipelineEventType.ERROR, {
                "code": "question-stt-failed", "message": "Could not capture the answer.",
            }))
    finally:
        try:
            if current():
                event_callback(PipelineEvent(PipelineEventType.RUN_END))
        finally:
            # Settle only the captured future, never a newer question. Silence,
            # disconnect, cancellation and failed STT are no answer, not an action.
            if not question.done():
                question.set_result(None)


async def async_run_protected_pipeline(
    hass, *, pipeline, context, audio_stream, event_callback, binding, ingress,
    handler, device_id, satellite_id, tts_audio_output=None, wake_word_phrase=None,
    silence_seconds=0.7, on_result=None, should_continue=None, on_speech=None,
):
    """Run on the admitting task; handler is trusted code, never client input."""
    admission = binding.admit(context)
    if admission is None:
        event_callback(PipelineEvent(PipelineEventType.ERROR, {
            "code": "protected-admission-denied", "message": DENIAL_SPEECH,
        }))
        event_callback(PipelineEvent(PipelineEventType.RUN_END))
        return
    text = None
    failed = False
    started = False
    intent_finished = False
    handled = None
    handled_reply = None

    def events(event):
        nonlocal text, failed, started
        if event.type is PipelineEventType.STT_END:
            text = (event.data or {}).get("stt_output", {}).get("text")
        if (
            on_speech is not None
            and event.type in {PipelineEventType.STT_VAD_START, PipelineEventType.STT_END}
        ):
            on_speech()
        if event.type is PipelineEventType.ERROR:
            failed = True
        # Two native runs are one satellite turn. Never send the STT run-end or
        # the TTS run-start: ESPHome treats run-end as the end of audio handling.
        if event.type is PipelineEventType.RUN_END:
            return
        if event.type is PipelineEventType.RUN_START:
            if started:
                return
            started = True
        event_callback(event)

    try:
        async with asyncio.timeout(max(0, admission.expires - time.monotonic())):
            with chat_session.async_get_chat_session(hass) as session:
                common = {
                    "hass": hass, "context": context, "pipeline": pipeline,
                    "event_callback": events, "tts_audio_output": tts_audio_output,
                }
                run = PipelineRun(
                    **common, start_stage=PipelineStage.STT, end_stage=PipelineStage.STT,
                    audio_settings=AudioSettings(silence_seconds=silence_seconds),
                )
                await PipelineInput(
                    run=run, session=session, stt_metadata=stt.SpeechMetadata(
                        language=pipeline.stt_language or pipeline.language,
                        format=stt.AudioFormats.WAV, codec=stt.AudioCodecs.PCM,
                        bit_rate=stt.AudioBitRates.BITRATE_16,
                        sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
                        channel=stt.AudioChannels.CHANNEL_MONO,
                    ),
                    stt_stream=audio_stream, wake_word_phrase=wake_word_phrase,
                    device_id=device_id, satellite_id=satellite_id,
                ).execute(validate=True)
                if failed or not isinstance(text, str) or not text or len(text) > 8192:
                    return
                speech = DENIAL_SPEECH

                async def handle(payload, original):
                    nonlocal handled, handled_reply
                    result, reply = await handler(payload, original, text, pipeline.language)
                    if type(result) is dict and type(reply) is str and 0 < len(reply) <= 4096:
                        handled, handled_reply = dict(result), reply
                    return result

                event_callback(PipelineEvent(PipelineEventType.INTENT_START, {
                    "engine": "codex_assist_protected", "language": pipeline.language,
                    "intent_input": text,
                }))
                result = await ingress.async_voice_turn(admission, transcript=text, handler=handle)
                if result == handled and handled_reply:
                    speech = handled_reply
                elif result.get("status") != "denied":
                    speech = FAILURE_SPEECH
                if on_result is not None:
                    await on_result(result)
                continuing = bool(
                    result.get("status") == "completed" and should_continue is not None
                    and should_continue()
                )
                event_callback(PipelineEvent(PipelineEventType.INTENT_END, {
                    "intent_output": {
                        "response": {"speech": {"plain": {"speech": speech, "extra_data": None}},
                                     "language": pipeline.language},
                        "conversation_id": session.conversation_id,
                        "continue_conversation": continuing,
                    },
                }))
                intent_finished = True
                if not failed:
                    tts_run = PipelineRun(
                        **common, start_stage=PipelineStage.TTS, end_stage=PipelineStage.TTS,
                    )
                    await PipelineInput(
                        run=tts_run, session=session, tts_input=speech,
                        device_id=device_id, satellite_id=satellite_id,
                    ).execute(validate=True)
                return result if not failed else None
    except asyncio.CancelledError:
        raise
    except Exception:
        event_callback(PipelineEvent(PipelineEventType.ERROR, {
            "code": "protected-pipeline-failed", "message": FAILURE_SPEECH,
        }))
    finally:
        # Remove an unconsumed STT lease too; revoking a turn never reopens ingress.
        ingress.discard_pending(admission)
        if not intent_finished or failed:
            event_callback(PipelineEvent(PipelineEventType.INTENT_END, {
                "intent_output": {
                    "response": {"speech": {"plain": {"speech": ""}}},
                    "conversation_id": "", "continue_conversation": False,
                },
            }))
        event_callback(PipelineEvent(PipelineEventType.RUN_END))
