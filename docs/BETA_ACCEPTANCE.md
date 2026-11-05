# Combined beta acceptance and rollback — not yet executed

This is a **checklist, not a result or permission to deploy**. All boxes below
remain open until evidence is recorded. Work in disposable amd64 HAOS first.
Backups, live cutover, restarts, key changes, profile assignments and recording
each need their own explicit approval. No data reset is necessary for packaging.

## Candidate record (complete before tests)

- Integration version + exact commit SHA: **pending candidate selection**.
- Add-on version + exact commit/build: **pending candidate selection** (`0.4.5` baseline).
- HAOS/Core, amd64 hardware, Android/Companion, Whisper and TTS versions: **pending**.
- HACS/Marketplace version, selected repository/ref and download/restart evidence: **pending**.
- Private backup identifiers and tested recovery method: **pending**. Do not upload
  backup files, internal addresses, tokens, profile names or audio with public evidence.

## Packaging / distribution

- [ ] Run `python scripts/check_distribution.py` and fast/native/mutation suites.
- [ ] Require all seven CI jobs on the exact candidate commit, including HACS,
  Hassfest, minimum Codex, current learning and strict HTTP fixture ordering.
- [ ] Verify the fork install link targets DaFern, not upstream; one integration
  directory includes learning Python, launcher JS, translations, brand and repairs.
- [ ] Test HACS download on a fresh test system. Confirm required non-Python assets
  survive download and match candidate bytes. A local projection check cannot prove
  HACS transport, installation, restart or frontend rendering.
- [ ] Verify candidate version parity/tag/ref, independent add-on version and
  prerelease status; no misleading default-catalog, released or acceptance claims.

## Clean installation matrix

- [ ] **Codex-only:** no Voice Match add-on, learning entry or Whisper dependency.
  Verify module menu, OAuth, existing personalities, harmless Assist, AI Task,
  reauth/reload isolation and the HA 2026.6 floor. Do not expose sensitive entities.
- [ ] **Learning-only:** no Codex account or entry. On HA 2026.10+, pair with an
  explicit learning key; test metadata suggestion and manual fallback; verify no
  OAuth, automatic pipeline/default change or recording at pairing/launcher time.
- [ ] **Both:** separate entries and keys; outage/reload/removal of one must not
  unload the other. Verify matching dedicated learning assistant and ordinary
  Whisper/TTS; leave existing assistants/default unchanged.
- [ ] Check observed Repairs and manual readiness for bridge/source outages,
  unavailable entities, duplicate/mixed pipelines and launcher conflicts. Unknown
  evidence must not count as fixed. Restore by explicit settings, never data reset.
- [ ] Test Codex personalisation separately, only after explicit opt-in: selected
  entry, distinct key, verified packet, neutral uncertain match and unchanged base
  prompt/Piper/AI Task. One enrolled speaker does not prove discrimination.

## Android and account/privacy acceptance

- [ ] Own account/profile required, even for administrators. Reject another login,
  account/profile mismatch, unassigned/ambiguous ownership and revoked/expired login.
- [ ] Native Learn/Resume opens the correct dedicated assistant. Verify unavailable
  native path/manual fallback, duplicate clicks, Back/reload and uncertain dispatch.
  Do not substitute HA's global preferred assistant for the previous client selection.
- [ ] Spoken notice and optional privacy details precede separate **Start learning**.
  Initial/control/consent turns are never training samples; ordinary Assist never trains.
- [ ] Complete **30 varied phrases** hands-free; only saved count advances. Rejected
  clips repeat the same phrase. Check end-of-speech, TTS echo and real audio quality.
- [ ] **Pause learning** retains unfinished samples. Same-login/account/chat resume
  previews status and requires **Continue learning**; changed/expired/interrupted
  scope requires fresh notice/**Start learning**. Never inherit a sample permit.
- [ ] **Cancel voice learning** discards only its bound unfinished session, keeps
  the installed voiceprint, and reports uncertain cleanup rather than retrying blindly.
  Obtain explicit test consent before this expected test-session deletion.
- [ ] Disconnect/reconnect, clip interruption, bridge outage and failed unload stay
  fail-closed. A failed unload is not successful disablement. Do not reset to hide it.
- [ ] Validated replacement installs before cleanup; failed generation preserves
  the old voiceprint and available samples. Confirm normal Whisper fallback.
- [ ] User manually selects the usual assistant afterwards; do not claim automatic
  restoration. Record device acceptance narrowly, not as proof for all phones.

## Existing-installation cutover and rollback gate

- [ ] Inventory current code revisions, entries, entity IDs, pipelines/default,
  panel ownership, key authority and active/paused sessions through supported APIs.
  Do not expose secrets or directly edit HA internal storage/registries.
- [ ] Obtain approval for protected Core/code and add-on/data backups and verify
  they contain the intended recovery scope. Copies of voice data remain sensitive.
- [ ] Describe exactly which installation/HACS repository would be replaced and
  which old learning entry would be disabled. Keep the old code and instructions
  available. No profile, sample, voiceprint or key deletion is implicit.
- [ ] Pause/verify unfinished work first. If cleanup or unload is uncertain, stop
  and inspect; do not force replacement or retry a mutation. Disable standalone
  learning only after separate approval; never run both learning implementations.
- [ ] Install the approved candidate, restart only with separate approval, and wait
  at least **60 seconds** before recovery checks. Verify Core, modules, ordinary
  assistants, selected pipelines, TTS and read-only readiness before recording.
- [ ] If unsuccessful, stop learning and restore the exact previous code/approved
  backup with the same care. Re-enable only the previous learning implementation
  after confirmed unload/restart; verify its own entities/pipeline/launcher.
  A code-only rollback does not undo config/data changes; restoring a whole backup
  can roll back unrelated work and keys. Explain that scope and get approval first.
- [ ] Recheck unchanged voiceprints/samples, ordinary Whisper, Codex personalities,
  AI Task, Piper, defaults and thresholds. Re-pair only if specifically necessary
  and approved; key rotation is not a normal rollback step.

## Publication gate

- [ ] Record clean-install and real-phone evidence for the selected candidate in
  issue #5; unresolved privacy/consent/cleanup failures block publication.
- [ ] Reconcile remaining standalone instructions only **after** replacement acceptance.
- [ ] Obtain separate version/tag/prerelease/publication approval. Follow
  [RELEASING.md](RELEASING.md); don't treat phase 4 preparation as approval.
