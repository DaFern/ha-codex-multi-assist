# Testing

## Prepared action-reply personality refinement

The owner reported after deployment that conversational follow-up now worked and a
light command gave useful device-specific feedback, but the reply lacked the desired
personality flair. This is owner acceptance of that conversation flow, not exhaustive
multi-speaker/privacy or physical-device verification. Its exact reply path was not
logged, so model generation versus factual fallback remains unknown for that request.

The refinement strengthens profile-specific wording guidance without forcing jokes
on minimal/serious profiles, and adds fixed-code INFO diagnostics distinguishing
generated replies from fallback reasons without logging personal content. The fast
suite passed 997 tests plus 32 subtests; five focused native readback/personality
contracts passed on each HA compatibility version. Changed-file Ruff passed. These
scripted tests establish guidance/routing/log redaction, not real-model wit. Full HA
suites were not rerun for this prompt/logging-only refinement; prior baseline failures
below remain. Publication and deployment evidence is tracked separately in issue #1;
these tests alone do not establish installation or live wording acceptance.

## Prepared device-specific action readback

`tests/test_action_verification.py` covers exact native call/result pairing, class-
checked tool origin, exposure/read-permission revalidation, delayed feedback,
one shared deadline, optimistic/unavailable/mismatching states, bounded targets,
partial failures, unsupported postconditions, setpoint-versus-room-temperature,
unit mismatch, duplicate/missing results, cancellation and named factual fallbacks.
Native ChatLog contracts cover immediate/delayed feedback through both native-first
and model-requested tools, original personality delivery, exact target evidence and
one execution. The nine-domain/five-personality matrix deliberately leaves states
unchanged and now expects device-specific unconfirmed facts, not invented completion.
These are synthetic devices/model responses, not live hardware/model acceptance.

The candidate check passed 993 fast tests plus 32 subtests, 599 current-HA
contracts (1 skipped) and 370 minimum-HA contracts (197 skipped). The same three
backend pipeline failures recorded below remained on current HA; no new native
failures remained after updating obsolete generic-response fixtures. The final fast
suite includes rejection of generic, invalid and failed personality generation.
Changed Python files and the 61-file distribution projection passed their checks;
the pre-existing full-repository Ruff failure below remained untouched.
Installation, restart, commit/push and GitHub implementation updates remain pending.

## Prepared neutral-voice dialogue continuity

The development candidate retains tool-free dialogue across neutral voice matches
without carrying profile identity/preferences or HA/MCP tool authority. Fast tests
cover repeated uncertainty, the same speaker returning, a different speaker,
tool-bearing history, agent/key/conversation changes, expiry and lost boundaries.
Native ChatLog tests check the question/answer sequence delivered to the model,
first-request ChatLog ID continuity and empty tool catalogs on repeated neutral turns.
These use stubbed model responses, not live
speech or real-model compliance. Deployment and restart require separate approval.

The candidate check passed 967 fast tests plus 32 subtests, 595 current-HA
contracts (1 skipped), and 366 minimum-HA contracts (197 skipped). Three current-HA
backend pipeline tests failed; all three also failed on an isolated clean `b141d66`
baseline. Full-repository Ruff also found an existing overlong line in
`tests_ha/test_speaker_automation.py`; changed Python files passed Ruff. The
distribution projection passed. These baseline failures were left unchanged.

## MCP read-only preview

`tests/test_mcp_client.py` exercises synthetic HTTP protocol/security boundaries.
`tests_ha/test_mcp_options.py`, `test_mcp_tools.py`, `test_mcp_history.py` and
`test_mcp_delivery.py` exercise supported options saving, real native schemas/results,
account revocation, cross-user history isolation and model/tool replay across agents.
The preview is HA 2026.10+; older lanes verify its setup gate and skip unsupported
native features. See [MCP.md](MCP.md) for explicit live acceptance limits. No real
server credentials, device calls, code deployment or restarts belong in these tests.

## Personality-aware action replies and attribute tools

The complete source checkout passed **916 fast tests plus 32 subtests**,
**583 native HA 2026.10.0 tests / 1 skipped** and **363 minimum HA 2026.6.0 tests /
193 skipped**. Ruff and the 56-file distribution projection passed. These are local
synthetic results for the complete checkout, not remote CI or real-model/device
acceptance. Separately, installed runtime bytes match the candidate, HA config
validation passed, and recovery following the approved Core restart was verified
after waiting at least 60 seconds. No live device commands were used to test wording.

Added reply contracts cover all outcome categories, arbitrary profile instructions,
category retention and fully rewritten replies without stock wording,
malformed/oversized/incomplete replies, unexpected
tool calls, stream closure, failure without retry and cancellation propagation.
Native tests cover nine device domains, success/failure, all four starter agents
and a custom profile, checking action-before-reply ordering and exactly one action.
They establish payload/routing boundaries, not actual model obedience or speech
style. Personality-generation failure must leave the factual result intact.

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

The prepared, uncommitted [action-control draft](ACTION_CONTROL.md) passed
868 fast tests plus 32 subtests, 536 current native tests / 1 skipped, and
345 minimum-version tests / 192 skipped locally. These results do not update
the exact-commit remote CI evidence above or imply deployment/live acceptance.

With the prepared read-only attribute feature added, local results were 893 fast
tests plus 32 subtests, 565 current native tests / 1 skipped, and 345 minimum-version
tests / 193 skipped. The focused attribute-provider module passed 29 current-HA
tests. See [ENTITY_ATTRIBUTES.md](ENTITY_ATTRIBUTES.md) for version/agent coverage.

The app's rebuilt admin layout and existing-profile Android launch are confirmed.
The owner reports the current combined phone journey passed **Privacy details**,
pause/resume, cancellation at the resume prompt, **30-sample replacement/cleanup**
and everyday Voice Match afterwards. This is owner-reported acceptance, not a new
instrumented run or proof of every failure/security path. Fresh-account setup,
multi-speaker/device tests, fault recovery, clean HAOS installation and rollback
remain open. [BETA_ACCEPTANCE.md](BETA_ACCEPTANCE.md) separates this current-installation
evidence from future candidate-specific qualification.

## Test ownership and covered contracts

The read-only attribute feature's focused coverage is described in
[ENTITY_ATTRIBUTES.md](ENTITY_ATTRIBUTES.md), including eight configured agents
and a newly added ninth. HA 2026.6 skips this native-provider test module because
the provider platform does not exist there; that skip is not feature acceptance.

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
   For native-first commands and shared result handling, inspect actual tool calls
   rather than treating personality speech as proof. Cover switches, lights, fans,
   locks, covers, climate, media players, scenes and scripts; exercise success,
   partial failure, unavailable/excluded targets, caller identity and no replay.
   Scripted fast/native coverage and the distinction between acknowledgement and
   hardware completion are described in [ACTION_CONTROL.md](ACTION_CONTROL.md).
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
