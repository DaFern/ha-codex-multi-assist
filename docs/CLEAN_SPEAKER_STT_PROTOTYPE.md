# Clean speaker-aware STT: isolated prototype

**Development only. Not registered, selectable, deployed or a supported HA metadata
API.** No config-flow, entry-platform setup or live pipeline is changed by this
prototype. It is a feasibility test, not a finished replacement for port 10352.

## Why the current header is visible

The stock Wyoming STT integration returns the transcript text to Assist. Assist
emits that text in `stt-end`; its chat frontend copies it into the user's bubble
before the conversation agent runs. Removing the encrypted header inside Codex
therefore protects model input but cannot clean the already displayed transcript.
HA 2026.10's `SpeechResult` contains text/status, not a supported speaker-context
field forwarded to the conversation agent. A frontend-only filter would leave
the underlying transcript/trace unchanged. This prototype does not patch Core,
edit the frontend, use invisible characters or read a shared last-speaker sensor.

## Candidate design

`VoiceMatchSttAdapter` wraps an explicitly supplied personalised Wyoming STT
entity. It forwards audio and advertises the source entity's languages, audio
formats and processing requirements unchanged. The add-on's encrypted wire format
and ordinary STT endpoint remain unchanged.

On a successful non-empty transcript, the adapter verifies the encrypted packet
with the paired entry's key and returns a `str` subclass containing **only the
spoken words**. The object has no packet/key/profile attributes. Standard repr,
JSON and frontend events contain ordinary text.

A private, entry-runtime-local registry associates the encrypted packet with the
exact text object and the exact asyncio task processing that pipeline request.
It is keyed by object identity, not text equality or a WeakKeyDictionary (two
people saying the same words must never collide). The Codex connector consumes
that association once, rechecks the current key/expiry/body binding, then uses the
existing entry-wide nonce replay protection, preference scoping and speaker-aware
automation dispatch. The current HA caller is not replaced with the speaker.

At most 256 pending objects are allowed per entry. Key changes fail closed.
Weak-reference cleanup, task completion/cancellation callbacks and an expiry timer
remove abandoned records even if HA retains clean transcript objects in traces.
A cancelling task cannot consume a packet and begin another model/action turn.
The clean text can remain in normal HA history; the private association cannot.

## Important limits

- **This relies on Python object identity surviving the server's STT-to-agent
  path.** It is not a documented HA metadata handoff. A future HA release may
  normalize/copy strings or use a different task and break it. Version-pinned
  pipeline tests are mandatory; passing current tests is not an upstream guarantee.
- A JSON/client boundary carries only plain text and loses speaker context. There
  is deliberately no lookup by words, time proximity, device or last speaker to
  recover it. Plain text follows the existing neutral/unverified path; a forged,
  copied, expired, already consumed or wrong-task carrier is rejected.
- Native HA sentence triggers can intercept clean text **before Codex**, even with
  local-first intent handling disabled. They do not acquire the private speaker
  condition. Avoid phrase conflicts with the dedicated Voice Match trigger. Tests
  explicitly establish this behaviour and cleanup of the unused handoff.
- Actual STT audio processing, recognition accuracy, Piper playback, Companion app
  display and physical satellites are not established by these tests.
- Voice recognition remains a preference hint, never authentication, authority to
  disarm an alarm, or a guarantee of calendar/conversation confidentiality.
- Pairing keys/preferences are not published in pipeline events by the adapter.
  This is not a claim of universal log/trace redaction or protection against code
  running inside the same HA process. Personal instructions still go to the model.
- The older encrypted-transcript path is retained. Installing code alone would
  not make an existing stock-Wyoming pipeline's user bubble clean.

## Test boundaries

The pure handoff tests cover one-shot consumption, identical utterances with
different profiles, JSON/copy/forged-object boundaries, wrong task/entry/key,
expiry, capacity and owner cancellation with retained traces.

The native HA tests call `async_pipeline_from_audio_stream`, from STT through
intent, on real HA pipeline/conversation/automation implementations. Only engine
lookup/configuration, external STT/model results and unused DSP imports are test
doubles. Audio enhancement/VAD is disabled; the DSP doubles raise if instantiated.
The local host lacks a C++ compiler to build those optional processors. TTS is
not executed (the contracts stop at the intent stage); its native pure-Python
imports are installed using each HA release's declared requirements.

Assertions cover clean `stt-end`/`intent-start` and JSON event payloads, intact
literal preferences/model input, concurrent identical sentences using native
`choose` conditions, replay/invalid/uncertain/empty results, cancellation before
model execution, STT-only cleanup, native sentence interception and disabled or
mid-recording changed pairing.

## Before any live rollout

1. Review this integration-specific handoff and the supported-version evidence.
2. Add separately approved opt-in configuration, source-entity validation,
   setup/unload/reload lifecycle handling and user-facing warnings.
3. Complete CI, obtain backup/deployment approval and separate Core restart approval.
4. Select the new adapter in an explicitly approved pipeline and visually verify
   clean transcripts on the Companion app and actual satellite response audio.
5. Test multiple real speakers/devices, phrase conflicts, uncertain matches,
   disconnect/cancel/reload, pairing rotation and rollback to ordinary STT.

No live settings, source engines, voiceprints, automations, Alexa routines, agent
personalities, permissions or AI Task defaults were changed for this prototype.
