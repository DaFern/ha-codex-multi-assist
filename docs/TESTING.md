# Testing

## Combined integration phase 4 (development distribution preparation)

`python scripts/check_distribution.py` performs read-only checks of the single
HACS integration directory, required learning Python/frontend/repair/brand assets,
fork manifest identity, English translation parity and manifest/project/lockfile
version alignment. It reports a deterministic source-projection digest, not a
built archive, HACS download or deployed version. Negative tests cover missing
assets, extra domains, symlinks, unexpected data files and metadata drift. This
check is part of the existing tests/lint CI job, not a publishing workflow.

Fork install links now target DaFern's custom repository; upstream wiki material
is explicitly shared-feature background. The separate add-on repository retains
the standalone companion path and tests its static setup guide link and baseline
version documentation. Source versions remain `0.7.0` (integration) and `0.4.5`
(add-on), not new release announcements. See [installation policy](INSTALLATION.md)
and the **unexecuted** [beta acceptance/rollback checklist](BETA_ACCEPTANCE.md).

Phase 3 exact-commit remote CI `42101173078` passed all seven jobs at `2f91599`.
It is historical evidence, not CI for the uncommitted phase 4 preparation. New
public documentation URLs cannot be accepted as published until commit/push;
HACS/Marketplace transport, clean HAOS installs and real-phone combined operation
remain separate gates. No release, deployment, restart, pairing or data reset is
part of phase 4.

Local phase 4 results: **771 fast tests plus 20 subtests passed**; native HA
2026.10 strict-order suite **365 passed / 1 skipped** (existing aiohttp rewrite
warning), and HA 2026.6 **252 passed / 114 newer-only skips**. All **53** paired
bridge/controller tests passed; all **10** recorded fast mutations were caught.
The distribution projection contains **51 runtime files** and is byte-identical
to the phase 3 runtime. Ruff, Node launcher and diff checks passed. The add-on
suite passed **203 tests with 4 built-engine-only skips**; synthetic Chromium
mobile/desktop checks passed, including the static setup guide with no horizontal
overflow or pairing/recording request. These results do not execute the clean
HAOS/HACS transport or actual Android acceptance checklist.

## Combined integration phase 3 (development only)

New contracts cover cached Supervisor metadata projection, explicit endpoint
selection before key submission, manual fallback, the final review before entry
creation and the learning options menu. Readiness and repair contracts use real
HA issue/flow managers, registry/pipeline APIs and the strict HTTP fixture order.
They verify read-only hello-only checks during active learning; missing/mixed/
duplicate assistants; source/launcher failures; stale configuration results;
entry isolation, dismissal retention and cleanup on removal; bound repair-flow
handoff; and explicit Codex selection without key copying or cloud sign-in.

The protocol, sample controller and exact-turn handoff remain pinned to the
reviewed source implementation. A check or repair is not recording consent and
does not exercise an actual Android microphone. Supervisor discovery is tested
with synthetic cached metadata, not a live Supervisor adoption transaction.

The earlier CI repair remains covered by the strict HTTP lane. Remote phase 2
follow-up run `42091269843` passed all seven jobs at `8408322`, including HACS,
Hassfest and the strict ordering check. That is not remote CI evidence for this
uncommitted phase 3 work. No release, live deployment, restart or data reset is
included in this development slice.

Final local phase 3 results: **744 fast tests plus 20 subtests passed**;
HA 2026.10 passed **365 tests with one older-version-only skip** in both
default and strict HTTP plugin orders. The strict order also emitted pytest's
existing aiohttp assertion-rewrite warning. HA 2026.6 passed **252 tests with
114 newer-only skips**. All **53** cross-repository encrypted bridge/controller
tests passed without dependency skips. The Node native-launcher boundary fixture,
Ruff and diff checks passed, and mutation checks caught all **10** recorded
token/tool mutations. These are isolated local development results, not remote
CI, live Supervisor discovery, Android acceptance or deployment evidence.

## Combined integration phase 2 (development only)

The moved learning suite is under `tests_ha/learning/`. It uses native HA
authentication, entities, registry, panel/HTTP APIs and Assist pipeline execution;
Whisper, DSP and backend replies are synthetic. Only the missing frontend asset
directory is substituted. Android/native opening is not simulated as a phone
acceptance result. The source backend fixture uses two samples for speed; the
add-on's real 30-phrase protocol/target is not changed.

Learning remains HA 2026.10+; older matrix entries skip these pipelines and run an
explicit unsupported-learning contract while retaining the full Codex contracts.
Setup tests cover learning without Codex, with Codex, bridge retry/recovery,
missing Whisper, separate reconfiguration, failed shutdown and Codex reauth or
unload during an active learning session. The launcher retains the original
browser/native-boundary fixture:

```bash
node tests/frontend_native_launcher.cjs
```

For a paired checkout and the add-on's isolated test dependencies:

```bash
python scripts/check_learning_addon_contract.py /path/to/wyoming-voice-match-ha
```

This test-only runner uses the moved client/controller against the add-on's real
encrypted bridge/voice-store implementation with synthetic DSP. It refuses to
count missing-dependency skips as success, changes neither checkout and includes
no production compatibility aliases. The fast suite separately pins the wire
codec byte-for-byte and the AST of unchanged safety-critical moved logic to the
reviewed source release.

No phase 2 deployment, data reset, restart, public release or real-phone
acceptance is implied by these development tests. Phase 1 remote CI passed at
`d80eef2` (run `42081553911`); that is not CI evidence for uncommitted phase 2.

Local phase 2 results: 727 fast tests plus 20 subtests passed; HA 2026.10 passed
341 contracts with one older-version-only negative test skipped. HA 2026.6 passed
252 contracts and skipped the 90 newer-only learning cases. All 53 cross-repository
encrypted bridge/controller tests passed without dependency skips. The Node
launcher boundary fixture and Ruff passed; the fast mutation checks caught all
ten recorded token/tool mutations. These were local results at publication;
remote CI subsequently failed as described below. Real-phone acceptance remains
pending.

### Phase 2 CI follow-up

Remote run `42085676218` at `2466814` failed Hassfest because `assist_pipeline`
and `http` were missing from optional dependency declarations. It also failed
four native HA 2026.10 tests even though the initial local native suite passed.

The HTTP difference was reproduced in a fresh environment installed from the
same requirements/override files. Pytest plugin discovery order can choose HA's
client fixture, which permits late route registration, or aiohttp's strict client
fixture, which freezes the router at the first connection. Explicit ordering
reproduced exactly the four remote failures:

```bash
python -m pytest -p homeassistant -p aiohttp tests_ha/learning -q
```

The fix declares both imports as `after_dependencies`, keeping them optional for
Codex. The pipeline/DSP fixture is separated from the probe WebSocket client, so
actual learning setup registers its real launcher before any client opens.
AI Task/media-source components used by combined tests are also prepared before
that connection; no Codex entities, credentials or provider replies are faked by
this preparation. The feasibility probe remains independently tested.

The strict client is not patched to unfreeze routes, and no assertion is removed
or skipped to hide the failure. CI now runs the learning suite with explicit
strict ordering as well as the normal full suite. Publishing and rerunning remote
CI for this follow-up are separate from the initial failed phase 2 run; neither
the local fix nor its tests imply deployment or real-phone acceptance.

## Combined integration phase 1 foundation (historical development slice)

The module foundation adds first-run menu selection before OAuth, a Codex-specific
duplicate-account guard, explicit rejection of unavailable/unknown modules,
entry-scoped platform setup/unload and recursive diagnostic redaction. Tests cover
both existing entries without a discriminator and new explicit Codex entries,
unavailable learning alongside loaded Codex, no learning-triggered OAuth, model
timer cancellation and options reload targeting. See
[the design and remaining gates](COMBINED_INTEGRATION.md).

The token-interleaving harness still mirrors the runtime: module dispatch and
Codex setup do not create or replace the token coordinator. Its weak entry-keyed
lock survives reload, as verified by the real-HA reload/removal contract. The
runtime/auth implementation and the model-checker actors were not changed.

That slice did not move learning or deploy it. Phase 2's separate development
coverage and remaining acceptance limits are described above.

## Minimal Voice Match request diagnostics (development)

The local fast suite passed **701 tests**. Full real-HA contracts passed **244
tests each** on **2026.6.0** and **2026.10.0**; Ruff passed. The paired add-on
passed **65 tests**, with **4 upstream-engine/container tests skipped** outside
the image. CI, new image builds and live request evidence remain pending.

Regression tests initially failed because the diagnostic tag did not exist and
the sender emitted no decision logs. New assertions cover matched/neutral/rejected
receipt, local prompt composition (including the unregistered clean-STT path),
identical sender/receiver tags, malformed Unicode/oversize inputs, and exclusion
of keys, tokens, voice/account names/IDs, revisions, transcript and prompt text.
Sender tests also retain packet-selection assertions for every fallback reason.
Both shared codec copies remain identical; the packet format is unchanged.

These diagnostics only show local selection, verification and composition; they
cannot establish provider delivery or compliance. No live logging levels, audio
thresholds, preferences or ownership were changed. Neither checkout was deployed.

## Clean STT request handoff (unregistered prototype)

See [CLEAN_SPEAKER_STT_PROTOTYPE.md](CLEAN_SPEAKER_STT_PROTOTYPE.md). New tests
first failed collection because the handoff module did not exist. The final local
fast suite passed **699 tests**. Full real-HA contracts passed **244 tests** each
on **2026.6.0** and **2026.10.0**; Ruff passed. Intermediate HA lanes and CI for
this prototype remain pending. No production deployment/restart was performed.

`tests/test_speaker_handoff.py` covers exact-object/task/entry/key binding, one-shot
consumption, identical transcripts, JSON/copy boundaries, forgery, expiry, capacity
and cancellation cleanup. `tests_ha/test_clean_speaker_stt.py` runs native HA
STT-to-intent pipelines and real speaker conditions. It verifies clean frontend
event/JSON text with intact model preferences, simultaneous identical commands,
invalid/replayed/uncertain/empty results, cancellation before a model turn,
STT-only cleanup, unchanged audio properties, disabled/changed pairing and native
sentence overrides that do not inherit speaker identity.

External STT/model outputs are synthetic and unused DSP imports are guarded
test doubles (constructing a processor fails the test). VAD/enhancement is off;
local processor installation was blocked by the absent C++ compiler. TTS native
imports use each HA version's declared pure-Python dependencies, but pipelines
stop at intent. These results do not establish microphone/recognition/Piper
performance, native frontend rendering or a supported HA metadata API.

## Speaker-aware automation conditions (development)

`tests/test_speaker_automation.py` covers per-request immutable identity capture,
reusing one profile across phrases, neutral/plain/manual inputs, forged trace
copies, mutable template fields, native Mapping variables, concurrent devices,
capacity, cancellation, exceptions and unsubscribe. Regression collection first
failed because the new speaker automation module did not exist.

`tests_ha/test_speaker_automation.py` uses native HA automation/trigger/condition
discovery, `choose`, caller context and conversation responses with only the model
stubbed. It covers replay/forgery rejection, plain requests not borrowing the last
speaker, simultaneous conversation requests, and no model replay after an action
failure. No live automation, production integration, add-on or Core was changed.
See [SPEAKER_AUTOMATIONS.md](SPEAKER_AUTOMATIONS.md) for operation and limits.

Local full contracts on HA **2026.6.0** and **2026.10.0** each passed **237 tests**.
Fast suite passed **694 tests**. This is not CI, editor/satellite acceptance,
speaker-accuracy measurement, or deployment. Intermediate HA lanes still need CI.

## Experimental Voice Match preferences (0.7.0)

New fast tests cover authenticated/encrypted packet parsing, replay/expiry/body
tampering, per-speaker/agent/conversation scope, neutral resets, later-concurrent-
turn exclusion, diagnostic key redaction, literal preference composition and
pairing options that preserve agent and AI Task settings. A fake-backed conversation
test verifies clean text/model input and unchanged HA caller identity.

Local Python 3.14 result: **688 passed**. An existing failure in
`test_ai_task_uses_shared_prompt_without_overriding_agent_profiles` was reproduced
in an isolated archive of unmodified HEAD: its fake entity lacked `entity_id`.
After explicit user approval, one fixture assignment supplied that ID; production
AI Task code was not changed. Ruff passes and the lockfile was refreshed. This is
the fast/fake-backed suite, not a real-HA contract run or a production deployment.

`tests_ha/test_voice_match.py` exercises real HA conversation/ChatLog types with
synthetic paired packets and a stubbed external provider. It checks speaker
switches, neutral fallback, literal non-rendered preferences and duplicate nonce
rejection. It is written but **unrun** here; run all supported HA contract lanes
before release. The existing auth model-check tests remain unchanged.

The paired add-on has local tests but no new container/live end-to-end run yet.
Real Ingress/role pairing, two people's voices, simultaneous devices, neutral
confidence handling, model-response behaviour and rollback still require testing.
Source/setup docs are in [VOICE_MATCH.md](VOICE_MATCH.md); external wiki publication
is pending until the reviewed repository changes are committed and pushed.

## Automated checks

```bash
uv sync --all-extras --dev
uv run ruff check .
uv run pytest -q
```

The fast suite under `tests/` uses lightweight Home Assistant fakes. Run the `tests_ha/` suite in an isolated Python 3.14 environment so it does not reuse the normal project environment:

```bash
uv venv --python 3.14 .venv-ha
uv pip install --python .venv-ha/bin/python -r requirements_test_ha.txt \
  --override requirements_test_ha_overrides.txt
.venv-ha/bin/python -m pytest tests_ha -q

uv run --isolated --python 3.14 --with-requirements requirements_test_ha_min.txt \
  python -m pytest tests_ha -q
```

`tests_ha/test_single_entry.py` verifies duplicate setup stops before authentication
and existing entries can complete reauthentication and reconfiguration. It checks
the reload request; the reload implementation is stubbed in these flow tests.

### Home Assistant version selection

CI tests compatibility boundaries rather than every monthly or patch release:

- **2026.6.0** is the minimum supported version.
- **2026.8.3** exercises the legacy converter immediately before the Probatio transition.
- **2026.9.0** exercises Probatio with the old tool-result API.
- **2026.10.0** exercises the current stable release with `ToolResult` and no converter exports.

These checks do not establish that every omitted release, including 2026.7,
has been tested. Add a version when a relevant API change or reported regression
makes it a distinct compatibility case. Keep the minimum and latest stable
targets, and retain an intermediate target while it covers a separate supported
API contract. Review the matrix with each monthly HA release and update the
stable pins together. All lanes also run weekly, but pinned weekly runs do not
discover new HA releases automatically.

The current test plugin, `pytest-homeassistant-custom-component==0.13.370`,
pins HA `2026.10.0b4`. The test-only override installs `2026.10.0` instead.
Remove that override when an aligned plugin version is available and verified;
do not silently test a beta while claiming stable coverage.

### Test ownership

Before adding a test, identify its observable contract, a credible regression,
and why existing coverage cannot catch it. Prefer extending a case at the
owning boundary over duplicating it at several layers. Do not add production
exports or wrappers solely for tests. Demonstrate regression tests failing on
the old code for the intended reason before fixing it.

The fast suite covers local behavior with lightweight fakes. The HA contract
suite exercises real framework types and lifecycle calls with external backend
responses stubbed. It does not establish live authentication or device behavior.

`tests/test_codex_stream_completion.py` checks the shared response completion
contract through an HTTPX byte stream. It covers EOF and `[DONE]` without
completion, text delivery before completion, held tool calls, image previews,
explicit backend failures, and stopping at completion without waiting for EOF.
Successful SSE fixtures must include `response.completed` explicitly; generic
fake transports must not add it automatically. Function-call fixtures must end
each call with its `response.output_item.done` item, which carries the full
arguments, because the client reads tool calls only from that event.

`scripts/probe_tool_call_events.py` checks that contract against the live
backend. It asks for two parallel calls to a harmless tool, records the raw
stream while the real client parses it, and reports counts and booleans only.
Run it when the tool-call stream handling changes or tool calls misbehave:

```bash
uv run python scripts/probe_tool_call_events.py --model MODEL_ID --dry-run
uv run python scripts/probe_tool_call_events.py --model discovered --sign-in
```

`--sign-in` runs the integration's own device-code flow and keeps the token in
memory; an integration-owned `CODEX_ASSIST_ACCESS_TOKEN` also works. A
`consistent` result means the response completed, every call announced by any
event ended in a completed item with JSON-object arguments matching its
`response.function_call_arguments.done`, call IDs were unique, and the client
yielded exactly those calls. A run where no function call was announced
reports `inconclusive`. Failures print only the exception type.

`tests_ha/test_stream_completion.py` checks incomplete conversation and AI Task
delivery, rejection of incomplete images without persisted media, native tool
execution only after completion, and auth retry only before visible output.
The existing search delivery cases check that hidden search rounds still allow
the single auth-refresh retry. Run these with both HA contract environments.

`tests/test_codex_text_recovery.py` exercises completed-message recovery through
synthetic HTTPX SSE streams. It checks exact suffixes, whitespace, item aliases,
multiple text parts, repeat completions, and explicit failure when recovery
would be ambiguous or reorder delivered text. The real-HA completion and search
delivery cases also check completed-only answers, silent terminal responses,
auth failures after recovered text, and no Sources card on success or failure.
An auth retry must discard native state from the failed attempt. All backend
responses in these tests are synthetic; passing them does not establish live
Codex behavior.

`tests_ha/test_conversation_errors.py` calls HA's public conversation API with
synthetic HTTPX responses and registered native test tools. It checks fixed
speech for HTTP, SSE, transport, quota, authentication, and tool exceptions;
safe replay history and conversation-owned logs; refresh and reauthentication
counts; cancellation propagation; and no action replay after failed synthesis.
Chained exceptions carry synthetic sensitive messages and a private traceback path.
Diagnostics distinguish backend failure, empty-answer, and incomplete-stream sites
by integration filename and line number, without source text or absolute paths.
Authentication failures without reauthentication use generic speech. Reauthentication
keeps its short guidance, and quota speech makes no temporary-recovery promise.
No conversation result may attach a Sources card. Existing search handoff coverage
also checks this after an earlier search round. The request assertions verify
that conversation error guidance reaches the backend with custom prompts and
either search setting.

These tests run in both HA contract environments. They do not prove model
obedience, filter tool-result payloads, or establish framework-wide log or trace
secrecy. AI Task assertions retain their existing error expectations. No live
backend or Home Assistant device is involved.

The tool-result regression runs a real conversation and checks the outgoing
Codex payload. On modern HA it removes only the deprecated property to prove
the integration does not rely on that compatibility shim.

`tests_ha/test_ai_task_delivery.py` owns AI Task delivery. It calls HA's public
`async_generate_data` API and `ai_task.generate_data` / `ai_task.generate_image`
services with only external Codex HTTP replaced by a synthetic SSE transport.
HA supplies the real task objects, chat logs, service selector schemas, results,
attachment resolution, image persistence, and signed media representation.
The cases cover plain text, structured data (including optional null omission
and disabling hosted search), a local PNG attachment reaching backend HTTP,
and image bytes plus configured metadata reaching HA's media store. Invalid-image
cases cover both services with an actual 10 MiB overflow and a targeted local-file
open failure. They require a service error, zero backend requests, no generated
media, and no synthetic private-path marker in delivered errors, tracebacks, or
Codex Assist logs. Home Assistant core can log attachment metadata at debug level;
these tests do not claim framework-wide log redaction. They do
not establish live authentication, backend image generation, camera contents,
or device behavior. The synthetic PNG is not evidence that a backend honored
the requested image dimensions.

These delivery cases also enforce all three feature flags through HA's
admission checks, replacing the fast test's numeric flag assertion. Its
entry-scoped identity assertions remain. Schema edge cases and auth/retry
coverage remain separate; this is not a broad test-pruning pass.

#### AI Task mutation evidence

`scripts/check_mutations.py` holds the mutation table. Each `ha` entry is a
temporary AI Task source mutation, the `tests_ha/test_ai_task_delivery.py` test
that must fail, and the failure text it must print. The script copies the
checkout, including uncommitted files, to a temporary directory and never writes
to the checkout itself. In the copy it first runs each test unmutated, and stops
if any fails. It then applies one mutation at a time and runs that test. Run it
with the current HA environment's python:

```bash
.venv-ha/bin/python scripts/check_mutations.py --suite ha
```

CI runs this suite in the Home Assistant 2026.10 job, and the fast suite (token
rotation and tool-call parsing, `--suite fast`) in the main test job. Each
mutation prints one status:

- `caught`: the test failed and printed the expected text.
- `SURVIVED (test passed)`: the test passed with the mutation applied. If the
  anchored code is now dead, or the contract is also implemented elsewhere,
  re-anchor. Otherwise the tests no longer catch that breakage. That is a test
  regression, so fix the test.
- `WRONG FAILURE (expected text not found)`: the test failed, but not with the
  expected text. Read the printed output. Update `expect` only if the new
  failure still proves the same contract.
- `anchor missing`: a code change removed the text the mutation replaces.
- `anchor ambiguous (N matches)`: the text now occurs more than once, so the
  script cannot tell which occurrence to mutate.

For either anchor status, re-anchor the mutation to the code that now implements
the contract. Do not delete or weaken the entry.

The older lanes also run with `probatio==0.11.2` installed alongside
`voluptuous-openapi`. This catches converter/serializer mismatches when both
packages are available. Codex Assist selects the converter used by Home
Assistant's LLM helper, rather than inferring it from installed packages.

```bash
uv run --isolated --python 3.14 --with-requirements requirements_test_ha_202609.txt \
  python -m pytest tests_ha -q

uv run --isolated --python 3.14 --with-requirements requirements_test_ha_previous.txt \
  python -m pytest tests_ha -q

uv run --isolated --python 3.14 --with-requirements requirements_test_ha_min.txt \
  --with probatio==0.11.2 python -m pytest tests_ha -q

uv run --isolated --python 3.14 --with-requirements requirements_test_ha_previous.txt \
  --with probatio==0.11.2 python -m pytest tests_ha -q
```

## Hosted-search compatibility

`tests/test_codex_client_web_search.py` covers the standalone search loop through
synthetic HTTP and SSE responses. It checks intermediate-text suppression,
search-call budgets, cancellation, auth and rate-limit errors, and streaming on
paths that cannot start another internal search round.

`tests_ha/test_web_search_delivery.py` exercises the real conversation and AI Task
owners with backend HTTP substituted. It checks search followed by URL opening,
final-only speech and task data, absent source cards, next-turn native replay,
HA tool handoff, and search-endpoint 401 refresh. The handoff and next-user-turn
checks require a unique searched fact and URL in the outgoing model payload,
without repeating either in the final answer. They also check complete search
call/output pairs, preserved reasoning and raw provider annotations, a single
HA execution, and private-state
redaction in HA logs, subscriptions, and traces. These tests do not establish
live endpoint acceptance or account/model compatibility.

Before releasing a search-path change, test the exact candidate against the real
backend with integration-owned authentication: a search, a direct URL open, a
follow-up question, and a search followed by a harmless HA tool. Confirm that
speech and task data contain only the final answer, and inspect retained history
for backend rejection on the follow-up. Do not borrow another application's
credentials. Keep tokens and raw native state out of test reports.

Replace `MODEL_ID` below with a model from the integration’s account-discovered
list. The probe requires an explicit model so it cannot silently test a retired
hardcoded default.

To exercise the integration's client-side search path, run:

```bash
uv run python scripts/probe_client_search.py --model MODEL_ID --dry-run
```

With separate live authorization and `CODEX_ASSIST_ACCESS_TOKEN` already set to
an integration-owned token, omit `--dry-run`. This probe performs a direct query,
a direct URL open, a model-selected search, and native replay. Its output contains
sanitized counts and booleans, not answers, URLs, tokens, or raw native state.
The probe requires every direct and model-selected search to return HTTP 200
with usable, nonempty normalized output. Errors, malformed output, and empty
results fail the gate even if the model still answers; direct-stage successes
cannot substitute for model-selected search success. Completion proves exercised
transport paths, not semantic answer accuracy.
The probe does not connect to HA or verify device effects, speech, or UI behavior.
Test those boundaries separately through the real owners.

When the hosted-search payload, model defaults, search delivery, or backend contract changes:

1. Run `uv run python scripts/probe_web_search_contract.py --model MODEL_ID --dry-run` and its tests.
   The probe checks the backend's built-in `web_search` tool. The integration does not use that
   tool (it runs search on `alpha/search`, see [ARCHITECTURE.md](ARCHITECTURE.md)), so the probe
   shows whether the built-in tool works again, not whether integration search works.
2. In Home Assistant, enable web search and ask a current-information question that requires search.
3. Check the spoken answer for raw URLs, markdown links, or a source block. Confirm
   the response has no separate Sources card. Custom API consumers no longer receive
   Sources metadata in `response.card`. Test speech and target-client behavior
   separately from backend response data.
4. Verify a long spoken answer completes without a new Codex Assist or audio error.
5. If an integration-owned OAuth token is available, run the sanitized live probe:

   ```bash
   CODEX_ASSIST_ACCESS_TOKEN='[ephemeral integration-owned token]' \
     uv run python scripts/probe_web_search_contract.py --model MODEL_ID
   ```

   The probe emits closed outcomes and booleans, not event names, key shapes,
   response text, search queries, URLs, identifiers, or credentials. Success
   requires `response.completed`, a completed search item, and a nonempty answer.
   Never borrow credentials from Codex CLI, an editor, or another assistant.

## Release-candidate install

1. Download the branch or tag archive to test.
2. Back up the installed integration.
3. Copy `custom_components/codex_assist` to `/config/custom_components/codex_assist`.
4. Restart Home Assistant.
5. Confirm the integration version and logs reflect the candidate.

To roll back, reinstall the latest stable release through HACS and restart Home Assistant.

## Assist smoke test

After restarting Home Assistant:

1. Confirm `conversation.codex_assist` exists.
2. Select Codex Assist in an Assist pipeline.
3. Ask a read-only question and ask it to list exposed entities.
4. Test one harmless exposed light.
5. Confirm sensitive entities remain unexposed unless deliberately allowed.

## Clarification follow-ups

`tests_ha/test_clarification_followups.py` calls public HA Conversation and AI Task
APIs with scripted HTTPX responses. Outbound-request assertions check that
clarification guidance accompanies default, custom, options, template, and extra
prompts without mutating stored prompts or accumulating across turns. They also
check search guidance, auth retries, native tool handoffs, and AI Task exclusion.

Separate characterization cases check native continuation for final `?`, ASCII
`;` (U+003B), and fullwidth `？`, retained conversation ID and history, and no continuation
after ordinary, action, or cancellation acknowledgements. Ellipses, periods,
trailing prose or quotes, and Arabic `؟` remain unchanged and do not continue.
A completed-message-only question still reaches speech and triggers native
continuation after search, without a separate Sources card. A fixed
clarification-then-`HassTurnOn` script checks zero calls before clarification and
exactly one call to a synthetic light service afterward.
The script never chooses a response based on the new instruction. This proves
request construction and HA routing only, not model compliance or real device
behavior. Run the file and the full suite in both HA contract environments.

Before claiming live clarification or ESPHome support, use an authorized test
instance with integration-owned authentication and complete these checks:

1. Record the candidate commit, HA version, selected model, pipeline language,
   satellite model and firmware, and search setting. Keep private identifiers out
   of shared evidence. Test the default prompt and the installation's custom prompt.
2. Ask an ambiguous read-only question. Check that the actual model asks one direct
   question as the final sentence with nothing after its question punctuation.
   Inspect `continue_conversation` and the conversation ID in the Assist result.
3. On the physical ESPHome satellite, confirm the microphone listens again after
   TTS. Answer without another wake word and confirm the same conversation resumes
   with the earlier question in context. A true result flag alone is not this proof.
4. With only harmless test lights exposed, give an ambiguous action. Confirm no
   action occurs before clarification. Name the target, then confirm exactly one
   intended action and no unnecessary closing question or extra listening cycle.
5. Repeat clarification and answer with "cancel" and "never mind". Confirm no
   action occurs and listening ends. Separately test the satellite stop control
   and the existing timeout without changing microphone or pipeline settings.
6. Check an ordinary answer and a completed action for a false continuation flag
   and normal idle behavior. Enable search and verify a clarification has no URLs
   or source text after the spoken question and no separate Sources card.
7. Test the languages used by the installation. HA's native check recognizes `?`,
   ASCII `;` (U+003B), and fullwidth `？`. Record other punctuation as a known limitation;
   do not repair output or force English to make the test pass.

Report observed failures as well as successes. Do not claim live model compliance,
physical microphone reopening, or timeout and cancellation behavior from the
scripted suite. Publish matching wiki guidance only after the repository docs
reach `main`, as required by [RELEASING.md](RELEASING.md).

## Authentication and model tests

The auth boundary regressions use real `httpx` responses and transport exceptions
for device-code requests, polling, code exchange, and refresh. Coordinator and
discovery tests use the real auth client to check temporary failures, unchanged
credentials, still-valid-token fallback, and authentication versus unavailable
classification.

The stubbed exchange-recovery case does not establish that a live one-time code
can be reused after a lost exchange response. Restart sign-in if pairing cannot
finish after an exchange failure.

`tests_ha/test_auth_recovery.py` drives HA's flow manager through setup, reauth,
and reconfigure failures, then resumes each flow. It also calls public Conversation
and AI Task APIs through temporary refresh failure and recovery, and opens options
with cached models after a failed refresh. External HTTP is stubbed; the options
cache uses an injected clock to advance its cooldown. Run this file in both HA
contract environments. These tests do not establish live sign-in or backend
availability.

When auth or model handling changes:

- verify invalidated credentials produce a clear reauthentication path;
- complete device-code sign-in and confirm the existing config entry resumes;
- confirm logs do not expose tokens, cookies, or device codes;
- verify fallback models appear when discovery is unavailable;
- verify authenticated model discovery when the backend supports it;
- verify an unlisted saved model is labeled and remains selected when other options are saved;
- verify discovery failure offers an explicitly unverified fallback only when no successful cache exists;
- verify a successful empty account list does not become a fallback list;
- verify setup asks for the model only after sign-in;
- verify concurrent refresh, 401 retry, cache invalidation after reauth, and periodic-refresh unload cleanup;
- verify new setup preselects the first advertised model, regardless of its model ID.

## AI Task and media tests

Home Assistant's normal Assist popup may not expose file uploads. Use AI Task surfaces for native attachment testing.

1. Confirm the Codex Assist AI Task entity exists.
2. Call `ai_task.generate_data` with a small local image or camera attachment and verify the response uses its contents.
3. Call `ai_task.generate_image` with a plain prompt and one non-default size.
4. Confirm text-only Assist still works afterward.
5. Confirm logs do not contain tokens, local file contents, or base64 payloads.

Codex Assist accepts up to four image attachments, with a 10 MiB per-image limit and
a 20 MiB aggregate limit per request. For nonblank instructions, missing paths,
unreadable images, and requests
over any attachment limit fail before a model request. OS errors must not expose
attachment paths in delivered errors or Codex Assist logged tracebacks. Non-image MIME types
remain ignored.

Repeat attachment checks through both AI Task services. Confirm a valid PNG reaches
the backend, then confirm an image over 10 MiB fails without a model request.
Fast boundary tests cover stat, open, and read failures, mixed valid and invalid
images, exact limits, and growth during a bounded read.

Before publishing screenshots, remove private URLs, account details, tokens, device codes, and private entity or dashboard names.
