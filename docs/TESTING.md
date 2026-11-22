# Testing

## Room music defaults — development only

Publication/deployment checkpoint: feature commit `2041ca0` was pushed to `main`.
With owner approval, 10 scoped integration files were backed up, installed and
hash-verified against that commit; Home Assistant configuration validation passed.
After the separately approved restart and 65-second grace period, Core reported
RUNNING, both Codex entries reported loaded, Supervisor was healthy and the satellite
was idle. No household room defaults or permissions were changed. Live UI/music
acceptance remains pending; the bounded startup log retained the known adapter
provider-import blocking warning and unrelated integration/template warnings.

Native options tests exercise area/player selection, save/remove, stale-room removal,
registry/platform/disabled-player validation, preserving unrelated/current options,
same-room concurrent-edit refusal and the entry-owned satellite settings provider.
Music API tests verify defaults beat an already-playing alternative, named-player
overrides, room aliases, inherited satellite/device areas, explicit entity area
overrides, no-default compatibility, immutable per-request routing snapshots and
search/candidate playback on the selected player. Missing/unavailable/unexposed/
disabled/unauthorised defaults never silently redirect. Guest factory/control tests
verify the same routing and no widening of filtered context or role rights.

Validation passed 1,101 fast tests plus 32 subtests; full-repository Ruff and the
83-file distribution projection passed. The focused options/music/guest/satellite
native selection passed 103 on current HA and 12 on minimum HA (12 skips, including
unsupported modern music features). Skips do not establish music support on old HA.
The existing paired RBAC guest/satellite-admission/policy selection also passed
282 cases on current HA; no RBAC source or household policy was changed.
Full current and minimum native suite attempts each reached the 120-second limit
without a completion result; no full-native-suite green claim is made. No physical
speaker, model interpretation, browser-rendered form or live permission was tested.
These are isolated development results, not live activation or physical acceptance.
The tests changed no saved household defaults or roles. Deployment/activation must
be verified separately; a successful file copy is not a running-code check.

## Consolidated ordinary capabilities and feedback (in progress)

New paired tests exercise exact context-bound light settings, fan speed,
thermostat temperature/HVAC/presets, ordinary blinds and generic TV/media
stop/mute/seek/shuffle/repeat/source controls. Invalid ranges/options/features,
security operations, doors/garages even for owners, hidden device classes,
read-only roles and unexposed entities remain denied. Curated state tests check
field masks and omission of arbitrary private attributes.

Music tests cover extended fixed playback actions. Model tests cover completing
multiple accepted calls, partial counts after a later failure and bounded argument
repair without effects. Native STT/tool/TTS tests stop a generic player plus dim
a light, including revocation before the second action and spoken partial feedback.
Fresh current native tests passed 776 (one skip), minimum native 466 (204 skips),
paired current 366, paired minimum 245 (121 skips), and fast tests 1,089 plus 32
subtests. The minimum paired run found a fan-feature import relocation; using the
public fan import fixed it and the compatibility rerun passed. Both source lint
checks and distribution projection passed. Unsupported-feature skips do not
establish protected-path support on old HA. Final curated-field/context rechecks
passed on current and minimum HA. With separate approval, 12 integration modules
were deployed with verified source/live hashes and rollback copies; HA config
validation passed. After the approved restart and the 65-second wait, both Codex
entries and RBAC reported loaded, Supervisor was healthy and the satellite was
idle. The bounded startup log still showed the pre-existing provider-import
blocking warning and unrelated template/integration warnings; no clean-log claim
is made.
Test doubles supply external recognition/model/TTS and device services, not
physical acceptance.

## General protected non-security interpretation

The new source adds shared natural-language/correction guidance, RBAC-filtered
room/device aliases and static group references, exact alias resolution and bounded
opposite-direction replanning before effects. It does not add new control domains,
raw service forwarding, recognition thresholds or STT/VAD changes.

`test_protected_interpretation.py` checks explicit on/off, pause/resume, relative
volume and next/previous contradictions plus unique exact/domain-scoped alias
resolution. Mixed/negated wording and near misses are deliberately not rewritten
by the veto. `test_protected_model.py` supplies a wrong then corrected model
proposal and verifies no wrong-direction effect. Guest-tool tests cover music
speaker/room aliases and all-or-nothing denial of a forbidden group member.

The paired reference tests use real HA area/entity registries and compiled RBAC
for room/area aliases, hidden labels/locations, group read access, hidden members,
nested/template groups and group-service denial. Native STT/model/tool/TTS tests
add wrong-direction replanning and exact-member execution from group IDs/names;
membership/exposure/alias changes before execution cause denial with no effects.
These are controlled external-provider proposals, not live model quality tests.

Focused current-native tests passed **60**. Full native reruns passed **767 with
one skip** on current HA and **466 with 204 skips** on minimum HA. Fast tests
passed **1,089 plus 32 subtests**. The five-file paired selection passed **333**
on current HA and **230 with 103 skips** on minimum HA. Both lint checks, diff
checks and distribution projection passed. Skips are not protected-path support.
Five modules were deployed with verified hashes and rollback copies; HA config
validation passed. After the approved restart and a 65-second wait, both Codex
entries and RBAC reported loaded, Supervisor was healthy and the satellite was
idle. Startup logs still contained the pre-existing blocking provider-import
warning and unrelated integration/template warnings, plus a satellite connection
warning just before its latest idle update; no clean-log claim is made. Physical
recognition quality and actual interpretation remain supervised acceptance checks.

## Persistent shared protected-satellite conversation (2026-11-21)

The owner approved eight seconds of hands-free listening after each reply, then
clarified that silence must not erase the conversation, history must survive
restarts, and different speakers should share only currently permitted context.
Seven integration modules were deployed with verified source/live hashes and
rollback copies after the owner-approved source work. HA configuration validation
passed; after the approved restart and a 65-second wait, both Codex entries and
RBAC reported loaded, the satellite returned idle and Supervisor was healthy.
The journal still reported the existing blocking provider-import warning; unrelated
template/integration warnings were also present. This is not a clean-log claim.

`tests_ha/test_protected_history.py` covers validated private atomic Store data,
restoration into a fresh journal, full-input visibility dependency filtering,
non-destructive omission of private turns, scoped explicit forgetting, finite
turn/message/character limits, data-only canonicalisation, durable pre-effect
music-choice consumption and both raised and silently logged storage failures.
`test_protected_conversation.py` checks the separate volatile microphone timer,
playback-completion boundary, late speech and stop phrases.

The paired real-native `tests/test_satellite_admission.py` now includes repeated
continuation flags and their actual ESPHome string serialization, playback timing
and fallback boundaries, silence cancellation without a spoken loop, explicit
stop versus forget, permitted cross-speaker history, owner-to-child privacy,
fresh journal/connection restoration with forged-evidence denial, two-turn music
selection with new tools, consumption/replay refusal, storage failure before
playback and owned callback restoration on replacement/de-enrollment.
External audio activity, STT/model/TTS and socket readiness remain simulated.

The five-file paired policy/admission selection passed **318 tests**, and the
fast suite passed **1,089 tests plus 32 subtests**. Fresh full native reruns passed
**744 with one skip** on current HA and **446 with 204 skips** on minimum HA.
Unsupported-feature skips do not establish protected-path support on minimum HA.
The native environments are HA 2026.10.0 and HA 2026.6, not the installation's
exact HA/aioesphomeapi pair. Source tests and storage restoration do not establish
physical microphone behaviour, music playback, cold-boot protection before Codex
setup, or end-to-end dialogue restoration across another restart on the actual satellite.

## Experimental protected existing-satellite source stage

The paired `test_satellite_admission.py` now includes the per-instance adapter
hook → native STT-only controller → private Voice Match handoff → real compiled
RBAC policy → bounded protected model loop → native service admission → native
TTS-only controller. It covers guest/child/adult/owner grants, forbidden targets,
unchanged Context, no native intent-stage entry, incomplete/forged input,
disconnect cancellation during STT/model handling, reconnect admission, changed
client/configuration and denial-hook takeover/restoration through reload.

**These are source-level end-to-end tests, not physical Kiosk acceptance.**
The original tests simulate ESPHome object shapes and authenticated network
connections. STT/model responses and TTS synthesis are external-provider stand-ins;
HA's stage controllers, handoff, role compiler and service admission run for real.
The follow-up below adds native ESPHome-class coverage but does not perform socket
authentication or physical-device acceptance.
`tests_ha/test_protected_model.py` separately checks complete-stream buffering,
query-tool replay, fixed-tool/schema validation and failure speech. None of this
authorises deployment, a Core restart or live device actions.

Adapter-stage validation passed 237 paired RBAC checks on current HA; minimum HA
passed 189 with 48 unsupported modern-tool/adapter skips. Full Codex native runs
passed 714 with one skip on HA 2026.10 and 424 with 203 skips on HA 2026.6.
After the final projection recheck and enrollment test edits, the focused native
guest/options/model selection passed 26; the fast suite passed 1,089 plus 32
subtests. Lint, diff and distribution checks passed. The full native runs preceded
those final focused edits and are not an exact final-tree full-suite run. Neither
ESPHome native-class validation nor a physical Kiosk turn was performed. No source
was committed/pushed, deployed or restarted.

### Approved constructor-guard redesign

`kiosk_lifecycle.py` adds an explicitly approved class-wide runtime constructor
hook, filtered to administrator-enrolled ESPHome config entries. It synchronously
installs the per-instance audio guard before construction returns to platform
setup. A replacement revokes old bindings and cancels active STT/model/tool work.
Closed owners continue guarding newly constructed instances during Codex reload;
a replacement owner takes over without restoring unrestricted Assist. Explicit
de-enrollment restores only the exact constructor/instance hooks still owned by
the adapter. Unenrolled entries are left untouched.

The previously strict-xfailed replacement regression is now an ordinary passing
test, parameterized for guest/child/adult/owner permissions and denied targets.
Further real native-class regressions cover active-model cancellation, stale
instance/binding denial, changed unique identity, construction while the owner
is closed, enrollment before platform entity creation, unrelated entries and
non-clobbering restoration when a peer has installed a newer constructor hook.
The paired current-HA selection passed **262 tests with no skips or xfails**.
Minimum HA passed 189 with 73 unsupported modern-tool/native-lifecycle skips.
The final lifecycle case also verifies that removing one enrolled owner leaves the
other protected, and that the original constructor returns only after the final
owner explicitly de-enrolls.

Fresh full Codex native suites passed 715 with one skip on HA 2026.10 and 424
with 204 unsupported/version-specific skips on HA 2026.6. Fast tests passed 1,089
plus 32 subtests. Both source lint checks, diff checks and distribution projection
passed. Skips do not establish support for protected tools on minimum HA.

This is an unsupported class-wide runtime patch, not a supported HA extension
point. It is neither a Core-file edit nor a global intent/service patch. Tests
control socket readiness and external providers; they do not prove cryptographic
authentication or physical Kiosk behaviour. The late-construction test proves
protection after enrollment is installed, not before Codex setup on a cold boot.
Whole-system startup ordering and physical acceptance remain deployment gates.
Publication does not activate this redesign: no live installation or restart was
performed during these source tests. Deployment requires a separate review.

### Initial native ESPHome-class follow-up (historical blocker)

With separate approval, installed `aioesphomeapi==46.6.0`,
`esphome-dashboard-api==1.4.0`, `bleak-esphome==4.0.0` and their resolved
dependencies only in `/data/v2/cache/opencode/codex-speaker-ha-current`.
USB discovery/serial proxy and optional audio-enhancement imports are test doubles.
The real native satellite, runtime, API client and connection classes are used,
including `handle_pipeline_start`, the native audio queue/stop path and runtime
disconnect/reconnect callbacks. Real library readiness fields are controlled in
tests; no cryptographic handshake, socket provenance or actual Kiosk is verified.

The native selection passed 11 tests. A strict expected-failure regression,
`test_replaced_native_entity_cannot_return_to_ordinary_pipeline`, confirmed a
**release blocker**: replacing the native entity loses the instance-only hook.
Its test-only ordinary-pipeline sentinel was reached. No unrestricted intent or
live service executed in that test. The old connection validator refuses the
replacement, but that does not protect a new entity that never enters the adapter.
Initial startup ordering remains another unverified gate. Do not deploy this
prototype as protected Kiosk access or treat the xfail as a passing security check.
A lifecycle design revision was required at that stage; no class-wide patch had
yet been approved. The constructor redesign above resolves this regression.
The full paired selection after that follow-up passed 248 checks with this one
strict expected failure and no skips. RBAC lint and both checkout diff checks
passed. Production integration source was unchanged during the dependency/native
test follow-up; only tests and development documentation changed.

`tests/test_guest_policy.py` covers provider version/shape failures and admin role
selection, removal and disable semantics without changing RBAC roles. Native
`test_guest_options.py` exercises the supported HA options editor; the old-HA branch
proves the unsupported option stays hidden. `test_guest_control.py` exercises real
native services with simulated admission/policy, including fixed on/off/music,
request-local search/playback, original Context preservation, replay and revocation.

The paired RBAC checkout adds real compiled-domain tests in `test_guest_voice.py`.
Its expanded `test_satellite_admission.py` pairs the real role compiler, private
neutral handoff, admission scope and guest tools, including domain removal,
caller/key/role changes, source loss, held tools after return, serialized/unbound
packet refusal and disconnect cancellation. Run it with both checkouts in the
namespace as described below; ordinary fixture skips are not integrated validation.
The real connection validator is still simulated, not proof of live Kiosk provenance.
Ordinary neutral conversation tests assert that neither the old entity-list option
nor the new role option grants tools without protected admission.

Fresh guest-stage validation passed 1,089 fast tests plus 32 subtests, the full
HA 2026.10 native suite (707 passed, one version-specific skip), and the full
HA 2026.6 native suite (424 passed, 202 unsupported/version-specific skips).
The paired RBAC guest/admission/existing-intent-policy selection passed 202 on
current HA with no skips, and 189 on minimum HA with 13 modern guest-tool skips.
Those skips do not establish guest-tool support on minimum HA. Full RBAC was not
run. Source lint and distribution checks passed; nothing was deployed or published.

## Satellite compatibility and denial regression checks

`tests/test_satellite_compat.py` requires every modern native capability, rejects
API-registration-only support, and verifies unsupported option saves leave settings
unchanged. Modern music/neutral-provider tests are explicitly current-HA-only;
`tests_ha/test_satellite_denials.py` runs on both minimum and current HA instead of
skipping the older-HA rejection boundary.

The native denial cases cover unsupported APIs, missing/invalid voice packets,
missing satellites, account mismatch/inactivity, empty neutral permissions and nonce
replay. They assert no tool discovery, model request or fixed device-service call,
unchanged original caller identity and unchanged target state. They exercise
synthetic native conversation requests, not the physical Kiosk transport or live
end-to-end recognised-user/guest RBAC enforcement. No transport or RBAC exception
is activated by these tests or the compatibility guards.

The repaired direct-Wyoming positive fixtures use the existing account-bound
packet helper. Separate unbound/mismatched-account cases retain ordinary dialogue
only, with no tools, personalisation or device-service calls; the runtime identity
check was not relaxed. Fresh full runs passed 1,068 fast tests plus 32 subtests,
687 native tests on HA 2026.10 (one version-specific skip), and 421 on HA 2026.6
(201 unsupported/version-specific skips). The paired-checkout RBAC
intent-surface/oracle/satellite-policy selection passed 95 on each version with
no skips. Full-repository Ruff and distribution projection checks also passed.
These are development checks, not deployment, physical audio or live Kiosk acceptance.

The Music Assistant satellite path has focused tests in
`tests_ha/test_music_control.py` for fail-closed API exposure, exact request
context binding, and the single-tool boundary. Run them with the HA-native test
environment described below. The tests do not exercise physical satellite
provenance, actual Music Assistant playback, or per-user service acceptance.

## Dormant ingress-to-command chain (not activated)

Fifty-one new cases in the separate RBAC checkout's `tests/test_assist_ingress.py`
exercise versioned registration, task-bound admission, actual paired clean-transcript
handoff/nonce verification, compiled dual-account policy projection and native exact
execution. They simulate authenticated server Contexts and trusted STT, not browser
login, physical audio recognition or real satellite provenance. No network endpoint
is registered by these modules or tests.

The selected cross-checkout ingress/oracle/context/intent/policy/schedule/location run
passed 191 cases on both current and minimum HA, with no skips. It includes forbidden
and mixed batches (zero commands), forged source/identity fields, unbound/unknown
speakers, serialized and cross-task handoffs, sequential/concurrent nonce replay,
caller/key changes across awaits, revocation after context and native preflight,
mutable-body freezing, concurrency, capacity/expiry and unregister/cancellation.
Ordinary Assist baseline denials are also checked while the prototype is registered.

Use the existing isolated native environments and expose both source checkouts for
this selection: prepend Codex's root to `sys.path`, import `custom_components`, then
append RBAC's `custom_components` directory to its `__path__` before `pytest.main`.
Two PYTHONPATH entries alone do not work because Codex's package shadows RBAC.
Cross-project fixtures intentionally skip when the Codex checkout is absent; a run
with those skips is not integrated-chain validation. Full native Codex and full RBAC
suites were not run. Deployment, actual authenticated transport, lifecycle setup,
protected resolver/model integration and device acceptance remain pending.

The full Codex fast suite remained 1,055 passed plus 32 subtests. Existing focused
native execution/voice/MCP/history selections passed 55 on current HA and 46 on
minimum HA (one unsupported-feature skip). Changed-file Ruff and the 65-file
distribution projection passed. The final handoff fixed the formatting-only E501
in `tests_ha/test_speaker_automation.py`; full-repository Ruff now passes. Including
that file, fresh focused native selections passed 59 on current HA and 50 on minimum
HA (one unsupported-feature skip); the fast suite still passed 1,055 plus 32 subtests.
The companion RBAC dependency is local-only at `f15140c`, by owner choice. This
publication checkpoint does not install it or enable any live routes, permissions
or restart. See [RBAC_ASSIST.md](RBAC_ASSIST.md) for handoff and admission limits.

## Protected exact-target execution stage (not activated)

The inactive native adapter has 43 new native contract cases, run against both
current and minimum HA. They cover exact light/fan on/off, duplicate names without
target broadening, forbidden/mixed batches (zero commands), rechecks inside native
execution tasks, revocation after preparation/preflight and between targets,
concurrent replay/independent speakers, copied/altered proposals, registry replacement,
expiry, capacity, unavailable providers, indirect targets, cancellation without native
timeout detachment, errors without retry, and refused native argument broadening.

The focused current-HA execution/voice/MCP/history selection passed 55 tests; minimum
HA passed 46 with one pre-existing unsupported-feature skip. The RBAC selected
oracle/context/policy/intent/schedule/location run passed 140 tests on each HA
environment, including eight new actual paired-packet/compiled-policy/native-execution
cross-checkout cases. Revoking either speaker or kiosk bindings, native permission,
activity, exposure or hidden-state rights after preflight denies execution. These
are synthetic local services, not commands to household devices.

The fast suite remained 1,055 passed plus 32 subtests; the distribution projection
passed with 64 files. Full native Codex and full RBAC suites were not run for this
stage. Changed-file Ruff passed; the full-repository Ruff run still reports the
pre-existing E501 at `tests_ha/test_speaker_automation.py:95` (left unchanged).
No ingress exception, model tool enablement, live integration installation,
permission change, commit/push or restart occurred. The boundary is service admission,
not revocation of already-admitted device I/O or working end-to-end parental controls.
See [RBAC_ASSIST.md](RBAC_ASSIST.md) for wiring and acceptance gates.

## Protected RBAC context stage (not activated)

The full fast suite passed 1,055 tests plus 32 subtests. Twenty-two new context tests
cover schema/data bounds, unavailable/revoked providers, hidden-field omission,
unknown/unbound speakers, concurrency, snapshot/turn/account binding, one-time model
delivery, refused HA templates and no tools/history/global prompt merging. In the
RBAC checkout, 132 selected projection/policy/intent/schedule/location tests passed,
including two cross-checkout native contracts with both current role policies and
the actual Codex consumer. Changed Python files passed Ruff. No full native Codex
suite rerun or full RBAC-suite claim is made for this stage. No model/provider
request, live account/policy edit, installation, commit/push or restart occurred.

The protected client routes and action execution guards are still incomplete; the
context stage must remain disconnected from live Assist. This does not establish
working tablet/satellite parental controls. See [RBAC_ASSIST.md](RBAC_ASSIST.md).

## Inactive RBAC policy foundation

See [RBAC_ASSIST.md](RBAC_ASSIST.md). The initial compatibility consumer has twenty
fail-closed tests for authenticated caller forwarding, missing callers/providers,
incompatible API versions, provider faults, revocation, invalid responses and shared
kiosk speaker/ceiling separation without HA Context replacement. The
development RBAC checkout's oracle plus existing policy/intent/schedule/location
regressions passed 121 tests. The unchanged intent-block tests remain passing.

This is not a complete protected Assist route: target-bound
dispatch, provider registration/ingress exception and opt-in satellite ceilings
remain unimplemented. The later context-stage work is recorded above. No RBAC/HA
settings or live source files were changed. The
new modules are not wired into runtime and must not be deployed as parental-control
functionality. No end-to-end tablet/satellite enforcement is claimed.

## Prepared conversational action outcomes for all personalities

The owner requested normal “I've turned it off” wording after a successful HA-state
check instead of “reports as”, with personality-appropriate uncertainty or failure
otherwise. The prepared refinement supplies per-target reply statuses independently
of agent identity, keeps technical verification internal, and updates successful
factual fallbacks. Sixteen scripted cases cover success, missing feedback, a result
not reached, and command failure across dry, friendly, theatrical and minimal profiles.
They prove evidence/guidance delivery, not live model obedience or physical feedback.

Validation: 1,013 fast tests plus 32 subtests passed; five focused native contracts
passed on each HA compatibility version. Changed-file Ruff passed. Full native suites
were not rerun for this wording/status-projection change; earlier documented baseline
failures remain. Publication and deployment evidence is tracked separately in issue #1;
these checks do not establish live wording or physical-feedback acceptance.

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
