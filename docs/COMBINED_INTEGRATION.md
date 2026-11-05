# Combined integration — development phases 1 and 2

Umbrella: [Voice Match issue #5](https://github.com/DaFern/wyoming-voice-match-ha/issues/5).
This document describes development work, not a released combined integration.
The running add-on and separate learning companion are not changed by this work.

## One install, separate lifecycles

Keep one HACS integration repository and the `codex_assist` domain. Each config
entry has an explicit `module`: `codex` or `voice_match`.
Existing entries without that discriminator are Codex entries; their stored data,
unique IDs, agents and options are not rewritten. There is still only one Codex
sign-in, protected by its existing unique ID. Removing the manifest's global
single-entry restriction does not enable additional Codex accounts.

The user menu selects a module before any network requests. Only the Codex route
requests OAuth credentials or discovers models. The learning route verifies an
encrypted `hello` with the add-on, then offers phone learning, off by default.
Pairing and enabling entities are not recording consent. It does not select or
create a pipeline, request Codex credentials or change a default assistant.

Entry setup dispatches before provider-specific lifecycle imports. Codex alone
forwards Conversation and AI Task, schedules model refresh and registers its
entry-specific options listener. `ModuleRuntime` records that entry's platforms;
unload uses those platforms only. Learning has its own `LearningRuntime`, bridge,
coordinator and optional phone runtime. Only an enabled learning entry forwards
STT and its non-LLM Conversation agent; it never forwards AI Task or schedules
Codex model refresh. Bridge or source unavailability retries only learning setup.
Unknown modules fail explicitly without starting cloud platforms.

The learning entry owns its options/reconfiguration and can be repaired without
Codex sign-in. Shutdown pauses bound unfinished work; it does not discard stored
samples or replace voiceprints. Unverified shutdown/restoration refuses unload
rather than forgetting the state. That refusal does not unload Codex. Conversely,
Codex unload, options reload or reauthentication do not replace the phone runtime.

Learning retains the standalone companion's **HA 2026.10+** requirement. Earlier
HA versions reject learning setup before using its phone APIs; Codex retains its
existing **2026.6+** floor. This is not a promise that learning works on older HA.

The OAuth refresh coordinator remains keyed by the config-entry object and
survives reload; it is **not** moved into unload-cleared `runtime_data`.
Diagnostics recursively redact credentials, prompts and personal bridge fields,
including mappings inside lists and tuples, without modifying configuration.

## Clean development setup (not a live cutover instruction)

1. Use HA 2026.10+ with the separate Voice Match add-on and an ordinary Wyoming
   Whisper source. This checkout contains one integration domain. Do not install
   both learning implementations against the same launcher/pipeline.
2. Add **Codex Assist → Voice Match learning**. Enter the internal add-on origin
   and its **learning** bridge key from its administrator page. This manually
   verifies encrypted pairing; it is not secure automatic discovery/adoption.
3. Leave phone learning off, or explicitly enable it and select ordinary Whisper.
   Do not select the add-on's filtering/personalisation endpoints as the control
   transcription source. The selector checks the Wyoming provider and language;
   administrators must still choose the correct ordinary Whisper connection.
4. In Voice assistants, create a dedicated **Voice Learning** assistant with both
   new Voice Learning entities from this entry and your usual TTS. Do not change
   the default assistant. The integration does not silently create a pipeline.
5. Use your own normal Companion login and an account-assigned voice profile.
   The add-on's existing Learn/Resume links still target `/voice-match-learning`.
   Opening Assist can start its initial microphone request, but only a separate
   post-notice **Start learning** permits sample submission. A retained paused
   scope needs preview and separate **Continue learning** confirmation.
6. Pause retains unfinished samples. **Cancel voice learning** discards only the
   bound unfinished session; the installed voiceprint stays until a validated
   replacement. Recognition is never account authentication.

The hidden, non-iframe launcher resolves entities by registry IDs under
`codex_assist`, not their names. Its read-only command is
`codex_assist/voice_learning/launch_info`; the JS lives at
`/codex_assist/voice-learning-launch-v1.js`. It rechecks the signed-in login and
own profile, requires exactly one enabled matching learning assistant, and keeps
the previous duplicate/stale-launch guards. It never overwrites another panel.
If the old companion still owns the shared URL, use manual selection until the
separately approved cutover; loading both is not a supported final installation.

Internal `voice_learning/manage` coordinator controls remain scoped to an entry
and the authenticated caller. No satellite adapter ships, and browser-supplied
device/account IDs cannot grant recording authority. They are not a general phone
recording API. Global WS/panel registrations retain no entry credentials; handlers
accept only loaded learning runtimes, not a Codex entry or a failed/removed entry.

## Next phases (not implemented here)

3. Guided pairing, Whisper/pipeline guidance, optional personalisation and repairs.
   Endpoint discovery is not trust. Keep learning and personalisation credentials
   separate; do not advertise zero-touch adoption without an authorised protocol.
   Select the personalisation-to-Codex association explicitly rather than using
   a global last-speaker or arbitrary first-entry lookup. Do not create a general
   recording or arbitrary service-call endpoint.
4. Reconcile HACS/install links, versions and beta support policy. HA 2026.10+
   is proposed for the eventual combined beta. Current support remains per-feature
   as described above; this move does not raise Codex's existing support floor.
5. Separately approve backups, live cutover, restart and real-phone acceptance.
   Do not delete voices, voiceprints or samples just because a clean reset is
   permitted. Identify every proposed deletion before approval. Remove obsolete
   companion installation instructions only when its replacement works.

No phase may change ordinary Assist traffic, Piper, agent personalities, AI Task
defaults or recognition thresholds as an incidental effect. Recognition remains
personalisation, not authentication. Preserve separate endpoints 10350, 10352
and 8099. Do not silently change the default assistant or promise unsupported
automatic restoration of the previously selected Companion assistant.

## Verification gates

Fast tests/lint and token-interleaving checks cover the unchanged Codex boundary.
Native HA 2026.10 tests load the moved entities and exercise real authenticated
WebSocket pipelines with synthetic Whisper, DSP and server responses, including
ownership/login rejection, exact-turn permits, progression, pause/resume, cancel,
disconnect and launcher discovery. Paired source logic is pinned to reviewed
release `7ce8f71`: the codec is byte-identical and core safety logic has matching
AST hashes. The test-only cross-repository runner also exercises the new client
against the add-on's encrypted HTTP bridge and voice-store fixtures.

Older HA matrix entries run Codex and explicit learning-rejection contracts; the
newer-only learning pipeline tests skip there. A skip is not learning acceptance.
Android native launch/actual audio, 30-sample real training, clean HAOS installs
and live recovery remain separate acceptance work. No beta publication before
those checks and the packaging/documentation reconciliation.

Later: Codex-only and learning-only clean installs, combined operation, bridge
outages, Codex reauth during learning, key changes, unload/reload isolation,
protocol parity across repositories, real-phone consent/progression/resume/cancel,
ownership rejection and rollback. No beta publication before clean-install checks.
