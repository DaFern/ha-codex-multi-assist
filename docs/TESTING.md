# Testing

## Automated checks

Run from a development checkout, not live HA:

```bash
uv sync --all-extras --dev
uv run ruff check .
uv run pytest -q
uv run python scripts/check_distribution.py
node tests/frontend_native_launcher.cjs
git diff --check
```

The fast suite uses lightweight HA fakes. Native contracts need isolated Python
3.14 environments with the pinned HA/plugin/dependency requirements:

```bash
uv venv --python 3.14 .venv-ha
uv pip install --python .venv-ha/bin/python -r requirements_test_ha.txt \
  --override requirements_test_ha_overrides.txt
.venv-ha/bin/python -m pytest tests_ha -q
.venv-ha/bin/python -m pytest -p homeassistant -p aiohttp tests_ha/learning -q

uv run --isolated --python 3.14 --with-requirements requirements_test_ha_min.txt \
  python -m pytest tests_ha -q
```

CI covers **2026.6.0** (minimum Codex), **2026.8.3** (legacy converter), **2026.9.0**
(Probatio/old tool-result API) and **2026.10.0** (current pinned ToolResult API).
Learning and direct Voice Match require **2026.10+**; older lanes explicitly reject
or skip newer features. Skips are not feature acceptance. Omitted monthly releases
are not claimed tested. Review stable pins on each monthly release; weekly pinned
runs do not discover new releases automatically. The current plugin pins a beta;
the requirements override explicitly selects stable 2026.10.0.

The strict HTTP fixture order matters: aiohttp freezes routes on first connection.
Learning/launcher and required components must be set up before opening the client;
do not unfreeze routes or weaken assertions to hide ordering failures.

For paired bridge/controller verification, using the add-on's isolated dependencies:

```bash
python scripts/check_learning_addon_contract.py /path/to/wyoming-voice-match-ha
```

The runner uses the real encrypted bridge/voice-store with synthetic DSP and refuses
missing-dependency skips. It changes neither checkout. Distribution checks verify
the single-domain source projection, required Python/frontend/repair/brand assets,
English translation and version parity; not HACS transport or installation.

## Current evidence boundary

The current runtime-source local suites recorded **819 fast tests plus 32 subtests**,
**460 current native tests / 1 skipped**, and **269 minimum-version tests / 192
skipped**. Runtime commit `013d69f` passed all seven remote CI jobs:
[exact-commit run](https://github.com/DaFern/ha-codex-multi-assist/actions/runs/42378505698).
These counts describe the current implementation baseline, not tests rerun by
reading this guide or a qualified release candidate.

Ordinary direct-connected assistant operation and the app's rebuilt admin layout
are confirmed on the test installation. Existing-profile Android launch and short
notice/timely pause-resume have narrow phone acceptance. Full current combined
30-sample replacement/cleanup, fresh-account setup, privacy details, resume-prompt
cancellation, clean HAOS installation and rollback remain open. Candidate release
acceptance must be recorded separately in [BETA_ACCEPTANCE.md](BETA_ACCEPTANCE.md).

## Test ownership and covered contracts

Before adding a test, identify its observable contract, credible regression and why
existing coverage cannot catch it. Extend the owning boundary rather than duplicating
every layer. Do not add production exports solely for tests. Demonstrate regression
failure against the old behaviour before fixing it. Synthetic provider replies do
not establish model obedience, live authentication or physical-device behaviour.

- **Multi-agent/AI Task:** CRUD and stable IDs, independent settings/session/history,
  retained primary identity, shared sign-in/token coordination and separate AI Task
  defaults. Native delivery uses actual HA APIs, task schemas, attachments, media
  storage and admission flags with external Codex HTTP replaced.
- **Stream completion:** explicit `response.completed` is required; EOF/`[DONE]`
  alone fails. Tool arguments come from completed output items. No action before
  completion, replay after visible output or incomplete image persistence.
  Completed-message recovery must preserve exact order/whitespace and reject ambiguity.
- **Errors/auth/models:** generic safe errors, cancellation propagation, single allowed
  auth retry, no action replay, actual flow-manager recovery, serialized refresh,
  entry reload/removal, model discovery/cache/fallback and retained saved models.
  Borrowed Codex CLI/editor tokens are never test credentials.
- **Hosted search:** final-only speech/task output, no Sources card, complete private
  native replay, actual searched facts/URLs retained for follow-up/tool use, bounded
  rounds, cancellation and search-endpoint auth refresh. External SSE is synthetic.
- **Voice Match:** private object/task/entry handoff, clean frontend events, direct
  loopback Wyoming protocol, metadata-only setup, saved opt-outs, no source migration
  on opening setup, bounds/endpointing/cancellation, names with empty preferences,
  neutral uncertainty, replay/key binding, speaker scope and identical concurrent words.
- **Automations:** request-scoped immutable identity, reusable conditions, native
  `choose`, caller context and dispatch without model replay on action failure.
  Ordinary native sentence interception does not inherit private speaker authority.
- **Learning:** independent modules, HA login/ownership rejection, fresh exact-turn
  permits, no consent/control samples, reconnect vs interrupted capture, pause/resume/
  discard, uncertain-outcome recovery, final completion wait, terminal reminder,
  launcher one-shot guards and read-only readiness/Repairs. No recording consent
  is implied by pairing, metadata discovery, launch or entity enablement.

Native pipelines use guarded DSP doubles where processors are not exercised and
synthetic audio/inference. Passing them does not prove VAD, TTS echo exclusion,
Piper playback, microphone reopening, speaker discrimination or frontend rendering.

## Mutation checks

```bash
uv run python scripts/check_mutations.py --suite fast
.venv-ha/bin/python scripts/check_mutations.py --suite ha
```

The script copies the checkout into temporary storage, checks the unmutated case,
then applies each anchored mutation there. `caught` requires the expected failure
text; a surviving mutation, wrong failure or missing/ambiguous anchor is not success.
Re-anchor to the current owner rather than deleting or weakening coverage. CI runs
token/tool mutations in fast tests and AI Task delivery mutations on current HA.

## Live smoke and recovery checks

Use explicit authorization, a pinned candidate, protected backups and harmless
exposed entities. Keep credentials, personal names, audio, private URLs and raw
provider replay state out of reports. Install/restart, recording, deletion and key
rotation require separate approval. After an HA restart wait at least 60 seconds
before recovery checks. Restore a known exact backup/revision, not an assumed
"latest stable" fork release. Code rollback alone does not undo config/data changes.

1. Verify agents/AI Task and model options; test one harmless Assist request per
   agent, separate personalities/history and simultaneous requests. Confirm sensitive
   entities remain unexposed. Test unchanged shared AI Task text and image behaviour.
2. Test integration-owned device-code sign-in, reauth/reconfigure, temporary refresh
   failure, discovery/cache recovery and unload isolation. Lost one-time exchange
   responses may require new sign-in; a stubbed retry does not prove reuse is safe.
3. Test actual hosted search, direct URL opening, follow-up and a harmless HA tool.
   Check final-only speech with no raw URLs or Sources card and valid next-turn replay.
4. On Companion/physical satellites, test clarification followed by answer, cancel
   and timeout. Native continuation recognizes final `?`, ASCII `;` and fullwidth
   `？`; other punctuation is not promised. Verify actual microphone reopening and
   exactly one intended action, not only a `continue_conversation` flag.
5. Run Voice Match with multiple consenting people/devices: clean visible chat,
   names/preferences, A→B→A scope changes, neutral ambiguity, concurrent utterances,
   outages, phrase conflicts, reload, key changes and ordinary Whisper rollback.
6. Complete the separate learning/account/privacy/install matrix in
   [BETA_ACCEPTANCE.md](BETA_ACCEPTANCE.md). No public beta before candidate gates pass.

AI Task accepts at most four images, 10 MiB each and 20 MiB aggregate. Missing,
unreadable or oversized image attachments must fail before backend delivery without
leaking paths. Exercise both `ai_task.generate_data` and `ai_task.generate_image`,
structured null handling, nondefault image size, signed media and normal Assist after.
Native Assist popups may not expose uploads; use AI Task surfaces.

## Sanitized backend probes

Select an account-discovered model explicitly; probes are not a source of credentials.
Start with `--dry-run`:

```bash
uv run python scripts/probe_tool_call_events.py --model MODEL_ID --dry-run
uv run python scripts/probe_client_search.py --model MODEL_ID --dry-run
uv run python scripts/probe_web_search_contract.py --model MODEL_ID --dry-run
```

Live runs need separate authorization and integration-owned authentication. The
tool-call probe supports `--sign-in`; search probes can use an integration-owned
ephemeral token. Never copy another tool's tokens. Output is sanitized counts and
booleans; no tool calls means inconclusive, not success. Client search requires
usable HTTP 200 results at every exercised stage. The built-in `web_search` probe
does not test the integration's `alpha/search` endpoint; test the actual owner too.
Probe success proves transport, not answer quality, speech/UI behaviour or device effects.
