# Combined integration — development phases 1 to 4

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
2. Add **Codex Assist → Voice Match learning**. Where supported, choose an address
   suggested from cached Supervisor metadata, or enter it manually. A suggestion
   grants no trust and causes no connection until you submit the separate key.
   Enter the internal add-on origin
   and its **learning** bridge key from its administrator page. This manually
   verifies encrypted pairing; it is not zero-touch adoption or key transfer.
3. Leave phone learning off, or explicitly enable it and select ordinary Whisper.
   Do not select the add-on's filtering/personalisation endpoints as the control
   transcription source. The selector checks the Wyoming provider and language;
   administrators must still choose the correct ordinary Whisper connection.
   Review the final setup guidance and explicitly submit to save. No entry is
   created merely by selecting an endpoint or viewing the final review.
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

Confirmed pause (including the safety-control pause), cancellation and validated
completion responses append: “If you're finished with voice learning, remember
to switch back to your regular assistant.” The original result and retention/
deletion explanation remain intact. Unverified pause/cancel outcomes keep their
warnings without claiming success. This is a spoken reminder only: it does not
switch assistants, change the preferred assistant or start another recording.

The hidden, non-iframe launcher resolves entities by registry IDs under
`codex_assist`, not their names. Its read-only command is
`codex_assist/voice_learning/launch_info`; the JS lives at
`/codex_assist/voice-learning-launch-v2.js`. It rechecks the signed-in login and
own profile, requires exactly one enabled matching learning assistant, and keeps
the previous duplicate/stale-launch guards. It never overwrites another panel.
If the old companion still owns the shared URL, use manual selection until the
separately approved cutover; loading both is not a supported final installation.

After a non-throwing native `assist/show` request, the launcher replaces the
underlying HA route with Voice Match management using in-page navigation, not a
WebView reload. Native Assist has no acknowledgement: this is a request followed
by navigation, not proof that Assist opened. It does not react to spoken pause or
cancel, dismiss Assist, change the preferred assistant or grant recording consent.

The optional `return_path` comes only from one cached Voice Match add-on whose
internal origin matches the configured bridge and whose public HA `app` panel
binds to the same safe slug. The browser validates the internal ingress path
again and rechecks the captured account, connection, auth and native bridge.
No browser-supplied return URL is accepted. Missing/ambiguous metadata, aliases,
HTTPS/custom origins or a missing public panel can prevent automatic return;
launch discovery still works without a return path. With a validated path,
**Back to Voice Match** remains available if dispatch throws or navigation fails;
otherwise the fallback is **Back to Home Assistant**. No failure retries the
native launch or re-enables the consumed launch button. Actual Companion overlay
behaviour remains a separate acceptance check.

Internal `voice_learning/manage` coordinator controls remain scoped to an entry
and the authenticated caller. No satellite adapter ships, and browser-supplied
device/account IDs cannot grant recording authority. They are not a general phone
recording API. Global WS/panel registrations retain no entry credentials; handlers
accept only loaded learning runtimes, not a Codex entry or a failed/removed entry.

## Guided checks and repairs (phase 3 development)

The learning options menu separates **Check setup**, phone settings, pairing
repair instructions and optional personalisation guidance. Checks report the
bridge, source, learning entities, dedicated assistant and launcher separately.
They do not verify account ownership, a voiceprint, recording consent or an actual
phone handoff. A provider/language check cannot prove that a Wyoming connection
is ordinary Whisper rather than a filtered endpoint; the UI says so.

Checks occur during observed setup transitions and on explicit request, not by
continuous network polling. A manual check makes a fresh bounded encrypted
`hello` only. It does not use `begin`, `permit`, `sample`, `resume`, `cancel` or
`discard`. A configuration change during that await returns **not checked** and
cannot clear issues for the newer configuration.

Repairs use stable IDs per learning entry. Bridge failure offers that entry's
Reconfigure flow after confirmation; source failure opens its own learning
options. Missing/unavailable entities, missing/duplicated/mixed assistants and
launcher conflicts offer instructions and a read-only recheck. An unresolved or
unknown result does not count as fixed. Reload retains unresolved issues and
their dismissal state; entry removal cleans only its own known issue IDs. The
implementation uses the pinned HA 2026.10 issue API rather than assuming newer
entry-ownership arguments are available. Disabled, missing, Codex or mismatched
entry/issue targets are not accepted by the repair flow.

The launcher recognises its own existing panel on reload, but never overwrites
another panel at the shared URL. No repair installs an add-on, starts a server,
rotates a key, submits a clip, deletes recordings, reassigns a profile, switches
assistants or creates/changes a pipeline. Failed unload is not displayed as
successful disablement. Correcting pairing or settings still uses its existing
explicit confirmation and reload path, including refusal of unverified cleanup.

Optional personalisation is a **guide**, not automatic pairing: explicitly choose
an enabled Codex entry, then use its existing personal-preferences options and a
separate personalisation key. The guide reads only whether a key is configured,
does not show/copy it and does not claim it is verified. No Codex entry means
learning can continue without one; the guide does not start OAuth. Actual packet
verification and prompt composition remain per turn in the existing Codex path.

## Distribution preparation (phase 4 development)

The [installation guide](INSTALLATION.md) now identifies this fork's custom HACS
repository, the independent add-on and per-module support requirements. The
[beta acceptance and rollback checklist](BETA_ACCEPTANCE.md) is deliberately
uncompleted: package preparation is not HACS transport, clean-install or phone
acceptance. A read-only distribution check verifies the runtime source projection,
assets, one-domain layout and manifest/project/lockfile parity. Source `0.7.0` is
unchanged; identify development builds by SHA until a distinct candidate is approved.
The add-on baseline is `0.4.5`; it is versioned separately. Retain standalone
companion instructions while combined replacement acceptance is pending.

## Remaining phase (not implemented here)

Secure automatic adoption/key exchange is still not implemented. Metadata
suggestions and manual cryptographically verified learning pairing must not be
described as zero-touch pairing. The learning wizard gives pipeline guidance,
not automatic pipeline creation. Speaker-aware automation configuration remains
a separate explicit opt-in, with no general recording/service-call API.

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
