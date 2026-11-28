# Configured satellite questions

This development change supports Home Assistant's native
`assist_satellite.ask_question` on an enrolled protected ESPHome satellite.
The initial compatibility path was deployed, but two physical answers produced
`stt-no-text-recognized`. Voice Match logged `empty_transcript` for both:
this does not distinguish upstream transcription failure from speaker filtering.
The revised separate-engine implementation requires its own deployment/restart
and physical acceptance.

## Authority belongs to the automation

The person configuring the HA question has chosen its answers and consequences.
Any person answering it, including an unidentified guest or child, may provide
an answer. This path does not check speaker identity, guest roles or personal
device permissions. HA retains native answer matching and response data, including
free-text answers when the automation deliberately configures that behaviour.

That authorisation is limited to the configured question and its consequences.
An answer such as “turn off the lights” is answer text, not a general command.
It does not invoke a model, normal intent recognition, sentence automations,
arbitrary services, protected device tools or the ordinary conversation history.
The caller must explicitly handle matched/unmatched answers and errors.

## Compatibility implementation

- `kiosk_adapter.py` recognises an already-pending native question and selects a
  separate capture path before ordinary protected conversation dispatch.
- The existing enrolled entity, encrypted ESPHome session, owning Codex entry
  and normal paired STT configuration remain pinned. These are device/transport
  checks, not speaker checks.
- In Codex options, **Configured satellite questions**, explicitly select an
  available ordinary Wyoming Whisper engine. No installation-specific entity
  is hardcoded. Leaving this unset disables capture; there is no filtered
  fallback. Saving preserves other options and reloads this Codex entry.
- The answer run uses an in-memory copy of the normal pipeline with only its
  STT engine changed. The stored/default pipeline, prompt voice and ordinary
  voice-command routing are not changed. Only the ordinary `whisper` and
  `faster-whisper` ASR program names are supported; Voice Match/proxy engines
  are rejected. The source, registry identity, config entry and language support
  are rechecked before delivering the buffered answer.
- `protected_pipeline.py` runs STT only. It buffers the final transcript until
  the original question and connection are rechecked, then passes plain answer
  text to HA's native question future.
- No voice packet is used to grant permissions or retained in conversation
  history. Question audio bypasses the paired Voice Match provider entirely.
- Capture is bounded to 30 seconds. Silence, errors, cancellation, disconnection,
  changed options/source or a replaced question do not deliver an answer to a
  newer request. Only the original future is settled.
- Normal voice turns retain their previous authenticated, role-filtered
  capabilities and exclusions. Exposing a script still does not make it
  callable through the protected voice tool set.

The separately included polite-closing work makes standalone “thanks” and
“thank you” speak “You're welcome.” before standby, without reopening the
microphone. Compound thanks-plus-command requests remain ordinary requests.

## Validation

- Revised separate-engine focused and paired current-native selection: 291 passed.
- Full fast suite: 1,110 passed plus 32 subtests.
- Minimum-HA question/closing selection: 71 passed, 20 unsupported-path skips.
- Full Ruff passed.

The cached native environments use HA 2026.10 and the minimum supported HA,
not the installation's exact HA 2026.11 build. Pipeline/STT/model/network
boundaries are simulated; paired cases use real native ESPHome objects and HA
answer matching, but do not establish physical microphone/device acceptance.
Minimum-version skips are not claims of protected-path support.

Before enabling automatic offers, physically test yes, no, unmatched/free text,
no reply, cancellation, disconnect and a subsequent ordinary command. Confirm
that questions work without speaker matching, while ordinary commands still
obey their existing permissions.

This fix does not add direct news-request routing, modify any news automation,
or resolve separate briefing-cache sizing concerns.
