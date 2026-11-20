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

DENIAL_SPEECH = "This voice request is not authorised."
FAILURE_SPEECH = "I couldn't confirm that request."


async def async_run_protected_pipeline(
    hass, *, pipeline, context, audio_stream, event_callback, binding, ingress,
    handler, device_id, satellite_id, tts_audio_output=None, wake_word_phrase=None,
    silence_seconds=0.7,
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

    def events(event):
        nonlocal text, failed, started
        if event.type is PipelineEventType.STT_END:
            text = (event.data or {}).get("stt_output", {}).get("text")
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
                    nonlocal speech
                    result, reply = await handler(payload, original, text, pipeline.language)
                    if (type(result) is dict and result.get("status") == "completed"
                            and type(reply) is str and 0 < len(reply) <= 4096):
                        speech = reply
                    elif type(result) is dict and result.get("status") != "denied":
                        speech = FAILURE_SPEECH
                    return result

                event_callback(PipelineEvent(PipelineEventType.INTENT_START, {
                    "engine": "codex_assist_protected", "language": pipeline.language,
                    "intent_input": text,
                }))
                result = await ingress.async_voice_turn(admission, transcript=text, handler=handle)
                if result.get("status") not in {"completed", "denied"}:
                    speech = FAILURE_SPEECH
                event_callback(PipelineEvent(PipelineEventType.INTENT_END, {
                    "intent_output": {
                        "response": {"speech": {"plain": {"speech": speech, "extra_data": None}},
                                     "language": pipeline.language},
                        "conversation_id": session.conversation_id,
                        "continue_conversation": False,
                    },
                }))
                if not failed:
                    tts_run = PipelineRun(
                        **common, start_stage=PipelineStage.TTS, end_stage=PipelineStage.TTS,
                    )
                    await PipelineInput(
                        run=tts_run, session=session, tts_input=speech,
                        device_id=device_id, satellite_id=satellite_id,
                    ).execute(validate=True)
    except asyncio.CancelledError:
        raise
    except Exception:
        event_callback(PipelineEvent(PipelineEventType.ERROR, {
            "code": "protected-pipeline-failed", "message": FAILURE_SPEECH,
        }))
    finally:
        # Remove an unconsumed STT lease too; revoking a turn never reopens ingress.
        ingress.discard_pending(admission)
        event_callback(PipelineEvent(PipelineEventType.RUN_END))
