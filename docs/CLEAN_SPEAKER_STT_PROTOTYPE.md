# Voice Match: one everyday STT choice

**Direct-backend consolidation is a development follow-up, not yet deployed.**
An explicitly enabled Codex entry registers one **Voice Match** STT entity on
HA 2026.10+. This is the former **Clean voice messages** entity with the same
unique ID and existing entity ID/pipeline bindings. Its setup
toggle defaults to enabled, while saved opt-outs remain off. Activation still
requires saving valid pairing/source setup; it never edits or selects a live
pipeline. The filename retains the original prototype name for existing links.

## Setup after separately approved deployment

1. Keep the ordinary Whisper/original assistant available for rollback. Pair the
   Codex entry's Voice Match personal preferences with the personalised sender.
2. On that **Codex entry**, choose **Configure → Voice Match**, leave it enabled
   (the default for an unsaved choice), and enter the add-on's internal hostname,
   personalised port (normally **10352**) and personalisation key. The learning
   key is separate and cannot substitute for this pairing. Personal instructions
   are optional; recognised names work with an empty instruction.
   Setup sends only a Wyoming Describe probe, never audio. The response must
   advertise `voice-match-personal`; this does not itself prove key pairing.
   Every incoming transcription packet is still verified with the pairing key.
3. Saving reloads this entry and stops its active clean-voice requests. It creates
   **Voice Match**, but does not alter your default assistant or any pipeline.
4. Only after explicit test-pipeline approval, choose that new STT entity with a
   Codex conversation agent from the **same entry**, and your usual TTS. Disable
   local-first handling and avoid native sentence-trigger conflicts (see limits).
5. Verify actual Companion chat bubbles and speech with multiple speakers/devices.
   Recognition is not authentication. No recording or re-enrolment is started here.

Disable **Voice Match** to remove its active STT entity and pairing while keeping
saved voices and the backend address. Saving this choice records an explicit opt-out, so the
toggle stays off when reopened. Older versions removed the setting on disable;
an absent setting now shows the enabled default in setup, but does not activate
the adapter until valid setup is saved. Existing options are not migrated.
Before disabling, switch the test pipeline back to its original STT; pipelines
are never changed automatically, so one still referencing a removed entity fails
until corrected. No recordings are deleted. Re-enabling uses the stable entity
unique ID. Publishing code, deployment and a full Core restart require separate
approval; after installation, changing these options only reloads this entry.

## Existing setups and redundant sources

No options or pipelines are migrated automatically. Existing source-based setups
keep working, including the older encrypted-transcript path. Opening setup can
suggest the existing personal source's hostname and port from HA's public config
entry/registry APIs. Only saving a successful direct-backend setup replaces the
saved source-entity dependency; the source entity itself is not changed.

Once the direct connection has been tested, review any remaining assistants,
source dependencies and external clients before disabling an unused STT entity
through HA's entity settings. If no longer needed, remove only its corresponding
Wyoming Protocol connection through the Integrations page, not the Voice Match
add-on. Keep a fallback and the ordinary Whisper source needed by enrolment.
There is no separate old-source review option or automatic removal. No add-on
rebuild or endpoint removal is required.

New setups register neither `voice-match` nor `voice-match-personal` as extra
Wyoming STT entities. Those backend ports remain available for compatibility.
Voice Learning is deliberately separate; this change does not hide unrelated
Google/Whisper engines or filter HA's native picker.

## Why the current header is visible

The stock Wyoming STT integration returns the transcript text to Assist. Assist
emits that text in `stt-end`; its chat frontend copies it into the user's bubble
before the conversation agent runs. Removing the encrypted header inside Codex
therefore protects model input but cannot clean the already displayed transcript.
HA 2026.10's `SpeechResult` contains text/status, not a supported speaker-context
field forwarded to the conversation agent. A frontend-only filter would leave
the underlying transcript/trace unchanged. This prototype does not patch Core,
edit the frontend, use invisible characters or read a shared last-speaker sensor.

## Design and lifecycle

`VoiceMatchSttAdapter` owns a private `PersonalBackend` connection for new setups;
legacy configurations still wrap an explicitly supplied personalised Wyoming STT
entity. The direct backend loads Core's Wyoming protocol component/dependency
without registering a Wyoming config entry or STT entity, rather than imposing
a global protocol-version pin on older Codex-only installations. It checks service metadata on
the same TCP connection before sending audio, propagates the advertised languages
and processing requirements, and accepts mono 16 kHz/16-bit PCM only. Upload and
receive run concurrently to retain early endpointing. Request completion or
cancellation closes the upload iterator and both child tasks. Audio is limited
to sixty seconds and requests to 105 seconds, including a five-second metadata
deadline. There is no retry. The wire protocol, filtering thresholds, optional
instructions and separate enrolment-consent boundary remain unchanged.

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

At most 256 pending objects and 256 active clean tasks are allowed per entry.
Key changes fail closed.
Weak-reference cleanup, task completion/cancellation callbacks and an expiry timer
remove abandoned records even if HA retains clean transcript objects in traces.
A cancelling task cannot consume a packet and begin another model/action turn.
The clean text can remain in normal HA history; the private association cannot.

Entry unload/options reload invalidates the old adapter generation, destroys
pending packets/timers/callbacks and cancels entry-owned clean tasks, including
recording, STT-to-intent handoff and model processing. Plain Codex tasks are not
selected by this cleanup. Existing nonce replay protection survives reload.
An old adapter fails closed even if its source later becomes available again.
Each new recording revalidates its backend/source; disappearance, source replacement,
mid-recording changes or peer failures produce no raw-header fallback or retry.
Missing backends only mark this STT entity unavailable, without taking the other
Codex entities offline. Direct backends receive metadata-only availability probes
every thirty seconds; legacy sources retain source-state change monitoring.

## Important limits

- **This relies on Python object identity surviving the server's STT-to-agent
  path.** It is not a documented HA metadata handoff. A future HA release may
  normalize/copy strings or use a different task and break it. Version-pinned
  pipeline tests are mandatory; passing current tests is not an upstream guarantee.
- A JSON/client boundary carries only plain text and loses speaker context. There
  is deliberately no lookup by words, time proximity, device or last speaker to
  recover it. Plain text follows the existing neutral/unverified path; a forged,
  copied, expired, already consumed or wrong-task carrier is rejected.
- The STT API does not supply the chosen conversation agent to the adapter. Setup
  therefore cannot enforce a pipeline pairing at the STT stage: use only agents
  from the same paired Codex entry. Another Codex entry rejects the private carrier;
  unrelated agents or local handlers can see ordinary words, not verified identity.
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
2. Review the default-enabled setup toggle, retained opt-outs, source validation,
   setup/unload/reload handling and user-facing warnings with their test evidence.
3. Complete CI, obtain backup/deployment approval and separate Core restart approval.
4. Select the new adapter in an explicitly approved pipeline and visually verify
   clean transcripts on the Companion app and actual satellite response audio.
5. Test multiple real speakers/devices, phrase conflicts, uncertain matches,
   disconnect/cancel/reload, pairing rotation and rollback to ordinary STT.

No live settings, source engines, voiceprints, automations, Alexa routines, agent
personalities, permissions or AI Task defaults were changed for this prototype.

## Activation review — 6 November 2026

The name-context follow-up also exercises this prototype with a recognised name
and with/without saved preferences. Synthetic native HA pipelines deliver the name
to the model while `stt-end`, `intent-start` and serialized events contain only the
spoken text. This does not enable the adapter or prove Companion-app rendering.

The first review retained the prototype as unregistered pending approval for an
opt-in implementation. That implementation was subsequently approved and prepared
in this checkout: default-off options/source selection, Codex-only STT lifecycle,
validation against Wyoming discovery metadata, safe source loss, cleanup and
cancellation now have native regression tests. Source/engine I/O in those tests is
synthetic; no real-phone, satellite or provider acceptance is claimed. Remote CI,
backup/deployment/restart approval and the physical acceptance above remain pending.

The object/task-identity handoff remains version-sensitive and is not a supported
upstream metadata channel. Installing the name change alone leaves existing
stock-Wyoming chat bubbles unchanged.
