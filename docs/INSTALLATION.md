# Installation and combined beta policy

## Status and versions

This is **DaFern/ha-codex-multi-assist**, a development fork of
[itsreverence/ha-codex-assist](https://github.com/itsreverence/ha-codex-assist).
It is not the upstream default-catalog HACS entry. No combined beta is published
yet. A green build is not real-phone or clean-install acceptance.

| Component | Source metadata | Install channel / requirement |
| --- | --- | --- |
| Combined custom integration | `0.7.0` in manifest, project and lockfile; record commit SHA too | This fork as a HACS **custom Integration** repository; one `codex_assist` domain |
| Codex module | HA 2026.6+; Python 3.14 supplied by HA | Codex-enabled ChatGPT account; no Voice Match dependency |
| Learning module | HA 2026.10+ | Separate add-on, ordinary Wyoming Whisper, TTS and normal Companion login; no Codex account |
| Wyoming Voice Match add-on | `0.4.7` plus exact source/build revision | Separate HAOS app repository; amd64 CPU only; locally built image |
| Standalone Voice Match Enrolment | Existing experimental companion | Retained for current installations/rollback; never run alongside combined learning |

Source metadata is not deployed state or a release announcement. `0.7.0` spans
development revisions, so record the tested SHA. Do not manufacture a release/tag
to make version strings appear newer. A future candidate must choose a distinct
version, align `manifest.json`, `pyproject.toml` and `uv.lock`, and mark its GitHub
release as a prerelease. Review tag syntax against HA/HACS before publication.
The add-on versions independently. Ordinary direct-connected assistant operation
and the rebuilt app's admin layout are confirmed on the test installation; these
do not establish full combined learning, clean-install or public-beta acceptance.

## Fresh test installation

These steps are for an explicitly approved, disposable test system. They are not
permission to replace a working integration. Keep backups private: they can contain
OAuth/bridge keys, biometric recordings and voiceprints.

1. Choose the acceptance case: Codex-only, learning-only, or both. Use HA 2026.10+
   on amd64 HAOS for combined-beta acceptance. Codex-only minimum-version testing
   remains HA 2026.6; do not attempt learning there.
2. Install HACS if needed using its [official instructions](https://www.hacs.xyz/docs/use/download/download/).
   In **HACS → ⋮ → Custom repositories**, add
   `https://github.com/DaFern/ha-codex-multi-assist`, category **Integration**.
   The [repository shortcut](https://my.home-assistant.io/redirect/hacs_repository/?owner=DaFern&repository=ha-codex-multi-assist&category=integration)
   only opens this repository. Download **Codex Multi Assist** after verifying
   the owner/revision. With no releases HACS uses default-branch files; record the
   resolved SHA. Disable automatic development updates for a reproducible test.
   Do not install the upstream repository too: it owns the same domain.
3. Restart HA only after installation approval. Add **Codex Assist** in Devices &
   services. Select **Codex assistants** for OAuth and the ordinary agent/AI Task
   path, or **Voice Match learning** for learning-only. Learning must never start
   Codex sign-in. Configure both by adding two entries, not two integration folders.
4. For learning, independently install
   [Wyoming Voice Match](https://github.com/DaFern/wyoming-voice-match-ha#install-the-add-on)
   through the **app/add-on store**, not HACS. Set its upstream to working Wyoming
   Whisper; reuse existing TTS. Verify source version/build locally. The add-on
   does not install Python into Core, create pipelines or transfer keys to HACS.
5. Follow [verified pairing and dedicated learning setup](COMBINED_INTEGRATION.md#clean-development-setup-not-a-live-cutover-instruction).
   Use the separate learning key and internal origin on **8099**, not the browser's
   Ingress URL. Create a key only if needed and explicitly approved; replacing a
   key invalidates existing learning clients. No automatic adoption is supported.
6. Use **Configure → Check setup**. Confirm the chosen source really is ordinary
   Whisper; provider/language checks cannot prove that. Manually create exactly
   one dedicated assistant with both learning entities and your usual TTS. Do not
   change the global default or ordinary assistants. Opening the launcher and
   enabling entities are not recording consent.
7. Everyday Voice Match is independent: on the Codex entry open **Configure →
   Voice Match**, enable it and enter the internal app hostname, **10352** and its
   separate personalisation key. Use **Voice Match** STT with a Codex agent from
   that entry and usual TTS. No extra Wyoming STT connection is needed. Personal
   instructions are optional. Keep **10350** ordinary filtering, **10352** paired
   STT and **8099** learning separate. A configured key is not verified voice evidence.
8. Complete the [acceptance checklist](BETA_ACCEPTANCE.md). Revert to ordinary
   Whisper/manual assistant selection if uncertain. Do not improvise retries of
   uncertain sample submissions, cancellation, deletion or key rotation.

The HACS name is **Codex Multi Assist**, while the integration/config-flow name
remains **Codex Assist**. The standalone companion is not a second required HACS
download. On HA versions using Marketplace, labels may differ; that installation
path remains unverified until tested. See the [HACS structure requirements](https://www.hacs.xyz/docs/publish/integration/)
and [custom repository instructions](https://www.hacs.xyz/docs/faq/custom_repositories/).

## Existing installations

**Stop before Download** if upstream Codex or standalone Voice Match Enrolment is
already installed. Two repositories cannot manage `codex_assist` independently.
Likewise two learning implementations compete for `/voice-match-learning` and
must not be active together. See [backup and rollback gates](BETA_ACCEPTANCE.md).
Retain the [standalone instructions](https://github.com/DaFern/wyoming-voice-match-ha/blob/main/docs/ENROLLMENT_COMPANION.md)
until combined learning works on the real phone. No migration, deletion or clean
reset is required merely to test packaging. Identify any future deletion exactly
and obtain separate approval before executing it.

## Beta support policy

- Planned combined-beta acceptance baseline: **HA 2026.10+ on amd64 HAOS** with
  compatible add-on, Whisper, TTS and Android Companion. This is not a promise
  for every future HA release, phone, hardware platform or speech environment.
- Preserve per-feature floors: HACS remains **2026.6.0** for Codex-only; learning
  rejects older HA explicitly. Do not raise the global floor to hide failed tests.
- Only reviewed, exact-commit CI and separately recorded clean-install/phone
  evidence can qualify a release. No beta publication before those gates pass.
- No satellite capture, ordinary-assistant spoken entry, automatic pipeline
  creation, automatic credential adoption or exact previous-assistant restoration
  is claimed. Android may remember Voice Learning; select the usual assistant manually.
- Recognition personalises replies; it is never authentication or authority for
  locks, alarms, purchases or private-data access. Existing personalities, AI Task,
  Piper, ordinary Assist and thresholds remain unchanged by installation policy.
