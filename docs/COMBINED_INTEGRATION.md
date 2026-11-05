# Combined integration — development foundation

Umbrella: [Voice Match issue #5](https://github.com/DaFern/wyoming-voice-match-ha/issues/5).
This document describes development work, not a released combined integration.
The running add-on and separate learning companion are not changed by this work.

## One install, separate lifecycles

Keep one HACS integration repository and the `codex_assist` domain. Each config
entry has an explicit `module`: `codex` or (reserved for phase 2) `voice_match`.
Existing entries without that discriminator are Codex entries; their stored data,
unique IDs, agents and options are not rewritten. There is still only one Codex
sign-in, protected by its existing unique ID. Removing the manifest's global
single-entry restriction does not enable additional Codex accounts.

The user menu selects a module before any network requests. Only the Codex route
requests OAuth credentials or discovers models. The learning route currently
ends with an explicit unavailable notice: it creates no inert entry and does not
pair, start recording, select a pipeline or request Codex credentials.

Entry setup dispatches before provider-specific lifecycle imports. Codex alone
forwards Conversation and AI Task, schedules model refresh and registers its
entry-specific options listener. `ModuleRuntime` records that entry's platforms;
unload uses those platforms only. Reserved learning entries and unknown modules
fail explicitly without starting cloud platforms. Working learning-only setup
and independent bridge retry/recovery still require phase 2.

The OAuth refresh coordinator remains keyed by the config-entry object and
survives reload; it is **not** moved into unload-cleared `runtime_data`.
Diagnostics recursively redact credentials, prompts and personal bridge fields,
including mappings inside lists and tuples, without modifying configuration.

## Next phases (not implemented here)

2. Move learning, its STT/conversation entities and native launcher together.
   Learning requires no Codex account. Bridge/source failures and cleanup must
   affect only its own entry, not Codex agents. Preserve bound recording permits,
   ownership checks, consent, pause/resume, cancellation and validated replacement.
3. Guided pairing, Whisper/pipeline guidance, optional personalisation and repairs.
   Endpoint discovery is not trust. Keep learning and personalisation credentials
   separate; do not advertise zero-touch adoption without an authorised protocol.
   Select the personalisation-to-Codex association explicitly rather than using
   a global last-speaker or arbitrary first-entry lookup. Do not create a general
   recording or arbitrary service-call endpoint.
4. Reconcile HACS/install links, versions and beta support policy. HA 2026.10+
   is proposed for the eventual combined beta; this foundation does **not** yet
   change the existing 2026.6+ support declaration or contract matrix.
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

Phase 1: fast tests/lint, token-interleaving checks, minimum/current native HA
contracts, module-menu/duplicate-account/unsupported-module tests and recursive
diagnostic-redaction tests. These prove the foundation, not working learning.

Later: Codex-only and learning-only clean installs, combined operation, bridge
outages, Codex reauth during learning, key changes, unload/reload isolation,
protocol parity across repositories, real-phone consent/progression/resume/cancel,
ownership rejection and rollback. No beta publication before clean-install checks.
