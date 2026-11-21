# RBAC-protected Assist development

## Consolidated ordinary-control overhaul — deployed, physical acceptance pending

The owner approved one capability-and-feedback overhaul after the audit found
prototype restrictions. New source adds music stop/mute/seek/shuffle/repeat,
typed light brightness/RGB/colour temperature, fan speed, thermostat target/
HVAC/presets, ordinary blinds and feature-checked generic media/TV controls.
The additive `VOICE_CAPABILITY_VERSION=1` API and `ProtectedDeviceTool` map each
typed action to one fixed service and validated arguments, never a model-selected
domain/service. Device options/ranges/features, native/RBAC permissions, exposure
and exact registry identity are checked on each target before service admission.
Whole-target-set preflight remains mandatory. Covers require an explicit ordinary
blind/shade/curtain/shutter/awning class; doors/garages/gates/unknown covers remain
denied even to owners. Locks, alarms, scripts and arbitrary service forwarding
remain unavailable. No roles or live permission settings are changed.

Curated read state includes permitted brightness, volume, temperature, options
and supported actions, not raw attributes. Compound tool batches complete all
requested calls or report exact partial counts. Shared per-request effect claims
prevent automatic retries of uncertain effects across different tools/aliases.
Invalid arguments get bounded model repair; safe tool errors and specific
action/target acknowledgements are spoken. A post-handler permission denial
cannot reuse an earlier successful reply. Plain personality text may style
responses, but HA/Jinja prompts are never rendered or treated as authority.

Unique active-speaker selection applies within the requested room. The durable
rolling window increases to 32 turns/64 messages/64,000 serialized characters.
The 30-second admission lifetime, bounded execution and complete-input history
privacy checks are **not disabled**. Separating response latency from fresh action
authority and safely scoped long-term summaries need a separately proven design.
Speech capture, recognition thresholds and the eight-second microphone window
are unchanged. Validation passed: 776 current-native tests (one skip), 466 minimum-
native tests (204 skips), 366 paired current checks, 245 paired minimum checks
(121 skips), 1,089 fast tests plus 32 subtests, lint and distribution checks.
Unsupported-feature skips are not protected-path support on old HA. No overhaul
source was activated before approval. After separate deployment/restart approval,
12 integration modules were installed with verified hashes and rollback copies at
`/homeassistant/codex-ordinary-overhaul-rollback-20261121T073639Z`.
HA configuration validation passed. After the approved restart and a 65-second
wait, both Codex entries and RBAC reported loaded, Supervisor was healthy and the
satellite reported idle. Physical voice/control acceptance remains pending.

## General non-security interpretation follow-up

After physical reports of incorrect lighting interpretation and incomplete
transcriptions, the owner approved a general solution across the existing supported
non-security capabilities, rather than device-specific patches. This follow-up
was deployed as five hash-verified modules across Codex and RBAC, with rollback
copies. HA configuration validation passed; after the approved restart and the
required wait, both Codex entries and RBAC reported loaded, Supervisor was healthy,
and the satellite reported idle. Physical interpretation acceptance is pending.

The shared model policy now prioritises current corrections, natural/near-match
phrasing, conversation references and permitted room/category/alias resolution.
Current state is evidence about the device, never proof of the requested direction.
Ambiguous missing action words still require a short clarification.

RBAC's additive `VOICE_REFERENCE_VERSION=1` API provides bounded reference data
under current read permissions, Assist exposure and hidden-field masks. It does
not widen any old policy API or create grants. Only fully readable static groups
with direct supported members are references; nested/template/partial hidden
groups remain excluded. On/off tools expand a supplied group ID/name only into
those exact members and then retain whole-batch and native per-member control
checks. Music uses the same catalogue for speaker/room aliases.

Reference metadata and the permitted satellite-room marker enter the saved
visibility dependency set; stale aliases, changed membership, exposure or hidden
fields invalidate their reuse. Before any effect, explicit opposite-direction
proposals are rejected as a whole batch and sent back for bounded model repair,
not silently rewritten into services. Invalid evidence and unsupported/security
tools still deny. The integration remains a finite capability set: no climate,
lock, alarm, arbitrary script/service or unrestricted native-intent forwarding is
introduced. Neither raw speech capture nor STT/VAD/recognition thresholds changes.

Focused current-HA native checks passed 60 tests and the expanded five-file paired
selection passed 333. These use controlled model proposals; they prove context
packaging, alias/member resolution, conflict vetoes and policy boundaries, **not
the real model's understanding of every spoken phrase or microphone capture**.
Full regression suites passed: 767 current-native tests (one skip), 466 minimum-
native tests (204 unsupported/version skips), 1,089 fast tests plus 32 subtests,
333 paired current checks and 230 paired minimum checks (103 skips). Lint, diff
and distribution checks passed. Supervised physical interpretation/capture
acceptance remains pending; skips do not establish old-HA protected-path support.

## 2026-11-21 supervised deployment and conversation follow-up

The initial protected adapter was published and deployed with explicit approval
on one existing satellite. A physical read-only turn reached the protected runner.
That is not acceptance of physical controls, music playback, cold-boot ordering
or general release readiness. The source-only checkpoints below describe earlier
stages and must not be mistaken for the current installation state.

The approved conversation follow-up passed source validation and was deployed
with verified hashes and rollback copies. HA configuration validation passed;
the approved restart recovered, both Codex entries and RBAC loaded, and the
satellite returned idle. Physical conversation/retained-memory acceptance is pending:
after each successful spoken reply, continue listening for eight seconds after
native playback completion. A device requesting its next pipeline before the
playback callback supplies the fallback listening boundary. Speech beginning
within that window may finish; silence and explicit “that's all”, “stop listening”
or “goodbye” end listening. Stopping music is not a conversation stop.

The owner revised the memory requirement: one **shared conversation per satellite**,
retained across speaker changes, silence, disconnects and Home Assistant restarts.
The microphone still closes after eight seconds or a stop phrase. Conversation
memory does not time out; it is a bounded rolling window, not an unlimited archive:
at most 12 complete turns, 24 plain user/assistant messages (32,000 serialized
characters) and ten bounded music candidates. “Forget this conversation” removes
only the current participant's currently permitted context.

`protected_history.py` uses HA's supported private, atomic `Store` API. Only
validated data is loaded/saved, with save read-back before publishing changes.
Each turn records a fingerprint of **every** filtered input entity/field/name and
its registry identity. A new speaker receives a prior turn only if their fresh
projection contains that entire input visibility. This deliberately withholds
possibly harmless dialogue when it cannot safely prove a free-form reply contains
no restricted details. Restricted turns remain stored for eligible participants;
they are not exposed to, or erased by, a less privileged participant.

Channel/registry identity separates different pipelines and replaced registry
records. Ephemeral playback hooks, timers and transport bindings do not survive a
restart. No old tool calls, private STT handoffs, Contexts, authorisations or tools
are retained. Every turn obtains a new single-use connection admission, same-task
private STT handoff, verified evidence, fresh policy projection and fresh tools.
Saved participant labels are attribution only; unidentified guests cannot be
distinguished from one another by those labels. Shared history never transfers
another participant's identity or action permissions.

Saved music choices are restored only under the same visibility check, consumed
durably **before** playback, and rechecked by the new request's fixed music tool
before service admission. A failed/unverified storage write prevents playback;
an uncertain or failed action is not automatically retried. Consuming before an
effect may lose a selection on interruption, but avoids resurrecting it on restart.
Private storage is not encryption: HA administrators and backups may access it.

Native-class tests simulate external STT/model/TTS and audio activity; they do
not establish physical microphone timing or socket authentication. The cached
native environment uses HA 2026.10.0/aioesphomeapi 46.6.0, not the installation's
HA 2026.11.1/aioesphomeapi 46.25.0. Physical hands-free continuation, silence/stop
behaviour and music playback remain supervised acceptance checks.

## Status: inactive protected-path development, not working parental controls

### Configurable guest domains (source only)

Codex's **Guest voice role (development preview)** selector stores only an existing
restricted RBAC role ID, Disabled by default. Administrators edit its Domains and
entity exceptions in the existing RBAC panel; no role, binding or live permission
is automatically created. The current capability set covers direct light/switch/
fan on/off and fixed Music Assistant search, candidate playback, transport, volume
and queue operations. Further role domains do not enable unsupported services.

The additive `GUEST_POLICY_VERSION=1` provider returns bounded admin role labels,
filtered state/name projections and fresh per-action decisions. Legacy
`async_check_access` and `async_check_satellite_access` are not widened. Hidden
identity/state, explicit denies, schedules, unavailable/replaced/group/template
targets, music groups and missing/full-access roles deny guest actions.

`SatelliteAdmissionRegistry.async_guest_turn` and the matching dispatcher method
bind scoped guest tools to the existing single-use connection admission and
post-admission private STT handoff. The original Context is preserved; the guest
music subclass never resolves or impersonates an HA account. Source/role/key/caller
changes, expiry, replay and disconnect revoke current authority. Native on/off
execution retains the whole-batch and inside-task checks. Recognition thresholds,
matched-user policy and ordinary free-text intent denials are unchanged.

### Experimental existing-satellite adapter (source only)

`kiosk_adapter.py` now connects the source contract to an administrator-enrolled
existing native ESPHome satellite's per-instance audio entry point. It is an
unsupported runtime hook, not a Core change, replacement integration or endpoint.
The trusted callback validates the actual server-held entity/runtime/client/
connection, configuration and registry identity, encrypted/authenticated readiness,
and selected entry-owned Codex agent/Voice Match STT. Plaintext/unsupported or
changed connections deny. Disconnect revokes leases and cancels pending STT as well
as active model/tool work. New connections require fresh admission. Closed hooks
deny during reload; only explicit de-enrollment restores the original method,
and only when the method is still the exact hook owned by that adapter.

The runner uses native `PipelineRun`/`PipelineInput` for STT-only and TTS-only
stages on the admitting task, combines their run events, and never enters native
intent recognition, sentence triggers, conversation history or general discovery.
The bounded protected model loop buffers complete responses, validates tools and
uses the existing entry token coordinator. No arbitrary service bridge is added.
`async_voice_turn` chooses own-user RBAC/native policy for a verified enrolled
speaker, or the selected guest role for verified neutral evidence; `async_guest_turn`
retains its neutral-only contract. The original HA Context is never substituted.
Candidate projection is bounded to 1,024 entities in provider batches of 32; fixed
action batches remain limited to 32. Additional domains remain unsupported.

**No live Kiosk connection is enrolled or deployed.** Paired tests reach the
installed source hook, native STT, real role compilation, fixed model/tool dispatch,
native service admission and native TTS. Network authentication, external STT/model
responses and TTS synthesis are stand-ins. The original test environment lacked the
optional ESPHome packages. The approved follow-up installed
them only in the cached test environment and passed 11 real native-class/audio-entry
checks with simulated readiness and external providers. It also confirmed a
replacement gap in the original instance-only design. The owner subsequently
approved a narrowly filtered **class-wide constructor runtime hook** as an explicit
exception to the earlier no-global-runtime-patches constraint. `kiosk_lifecycle.py`
installs each enrolled replacement's instance guard synchronously before returning
the entity to native platform setup. Old connections and active work are revoked;
closed owners guard replacements during reload. The guard can enroll from saved
registry identity before an entity exists and leaves unrelated entries untouched.
Only exact owned constructor/instance hooks are restored on explicit de-enrollment;
a newer peer hook is never overwritten.

The formerly xfailed replacement regression now passes for matched/guest grants
and denials. The current paired selection passes 262 tests without skips/xfails.
This remains an unsupported runtime patch, not a Core-file edit or global
intent/service interception. Cold-boot ordering before Codex setup, actual socket
authentication and physical-device acceptance remain unverified deployment gates.
Ordinary unmatched conversation turns still deny control, including when a role is
selected; the old entity-list fallback remains disabled.

### Source-only satellite admission/execution contract

The separate satellite path now connects RBAC's `satellite_admission.py` to
Codex's `rbac_satellite.ProtectedSatelliteDispatcher` and the existing exact native
execution guard. It uses the satellite-policy interface: a positively unmatched
paired result selects the explicitly configured guest role; a matched result
selects its enrolled user's own RBAC/native permissions, without a kiosk ceiling.
The owner retains full supported access. Missing/unbound matched users do not
fall back to guests. The existing kiosk path is unchanged.

An authenticated transport integration must explicitly register an enrolled
satellite's actual connection and a synchronous connection-liveness validator.
The registry checks device registry identity, connection liveness, original Context,
owning task, expiry and single-use admission. Only one pending/active audio turn
per task is accepted. The paired private STT handoff must be issued after that
admission on the same task; raw/serialized packets and supplied user/device IDs
are not admission evidence.

Dispatch accepts only bounded exact light/fan on/off proposals. It rebuilds readable
RBAC context, rejects mixed forbidden batches, and rechecks policy and source
liveness inside every native service task. Disconnect/unload revokes before
cancelling; asynchronous teardown waits for the native child work. Cancellation
propagates, uncertain device errors are not retried, and already admitted actions
cannot be rolled back. Results expose fixed status/count only.

**No live transport registers this path.** The tests simulate authenticated sessions;
they do not authenticate network/audio hardware. An actual transport adapter must
enter the protected path *instead of* the ordinary pipeline's pre-agent sentence
triggers/local intents. There is no global patch, event-based identity inference,
baseline Assist exception, model tool, free-speech resolver or enabled ESPHome
interception. Existing live satellite routing is not secured by this source work.
The paired protocol currently encodes explicit neutral results as v1; recognized
v1 profiles lacking an enrolled account remain denied.

## Handoff checkpoint

This batch is a source-only development checkpoint for issue #4. The companion
RBAC changes were committed locally as `f15140c` in the separate `ha-rbac` checkout.
The owner explicitly chose **not** to fork or push RBAC; its origin remains the
read-only upstream repository. The Codex commit does not contain or install those
RBAC modules. Missing RBAC contracts fail closed. No versions, live files, account
permissions, routes or runtime registrations changed; nothing was deployed/restarted.

Resume in the Codex checkout plus that local RBAC checkout. Next work needs an
actual authenticated transport and trusted source binding, protected native/model
target resolution, reviewed lifecycle wiring and administrator setup before any
narrow ingress exception or end-to-end device acceptance. Keep ordinary Assist
denials and tools-free model context intact. Typed MCP/calendar issue #8 remains a
separate unresolved task; this prototype does not grant MCP/AI Task authority.

The final formatting-only E501 fix passed full-repository Ruff. Fresh validation
passed 1,055 fast tests plus 32 subtests, 59 focused current-HA native tests and
50 minimum-HA tests (one unsupported-feature skip). The previously completed
191-case cross-checkout selection passed on both HA environments; full native
Codex/full RBAC suite and physical-device acceptance remain unverified.

Development sources are in this checkout and the separate `ha-rbac` checkout.
Nothing has been deployed or enabled. There is no new integration, external
endpoint, role assignment, shared-satellite login, policy editor or bypass of
RBAC's existing conversation/Assist denials.

`rbac_policy.py` is a tested, version-checked consumer of the proposed RBAC
`assist_policy.py` in-process API. It forwards only the actual authenticated
tablet caller, never an identity supplied in text/tool arguments. Missing caller,
provider, incompatible version, malformed result and timeout deny permission.
Cancellation propagates. No decision is cached or reused across requests.

The RBAC-side oracle intersects currently assigned RBAC policies, native HA
permissions and, optionally, an explicitly restricted ceiling account. Missing
bindings cannot inherit HA's default user group. Owner/system/full-access accounts
cannot serve as restricted authority. It checks read/control separately and can
refuse hidden attributes. Control is limited to direct light/fan on/off; groups
advertising member IDs, scripts, scenes, automation triggers and other actions are
denied at this stage. Role schedules/location/deny semantics stay in RBAC's evaluator.

This oracle is not authentication or an execution capability. It assumes identities
come from trusted server code. It does not itself filter state/context or bind the
checked targets to subsequent intent execution. Calling it and then forwarding free
text to an unrestricted intent tool would still be unsafe.

## Implemented context stage

`rbac_context.py` now builds a separate bounded snapshot using RBAC's versioned
`CONTEXT_API_VERSION=1` projection. For each configured candidate, the provider checks
HA Assist exposure, native read permission and **both** current RBAC policies before
projecting state. Missing bindings, inactive/system/owner/full-access accounts,
provider loss or errors discard the snapshot. The projection performs no await after
resolving accounts and evaluating policy; hidden identifiers/states remove the row,
and a name hidden by either actor is not reconstructed from aliases or State.name.

Only explicitly requested, domain-curated scalar attributes are eligible; metadata,
credentials, reference/member lists, registry/area/floor information and nested
values are excluded. Hidden fields are omitted rather than labelled with their
values. Up to 32 candidates, 16 requested fields, a two-second provider wait and a
16-KiB final JSON limit apply. A malformed/oversize projection is unavailable, not
partially exported or replaced by unrestricted live context.

The model-envelope builder binds a validated snapshot to the exact caller Context
and prepared voice request, checks the caller has not changed and consumes the
snapshot once. It includes only projected JSON plus the current user question,
literal administrator-reviewed personality text and fixed data-handling guidance.
It accepts no old ChatLog, raw system/extra prompt, personal preferences or tool
results. HA/Jinja template personality prompts are refused, not rendered with global
state access. Tools remain empty until protected ingress/dispatch is complete. No model call,
public route or live hook has been enabled. A snapshot is still point-in-time data;
revocation cannot retract information already sent, and each delivery must rebuild it.
`async_prepare_shared_model_payload` combines the fresh policy projection and envelope
assembly without an intervening await and accepts no cached snapshot. Future dispatch
must use that entry point and must not append other context or tools.

## Implemented exact-target execution stage (inactive)

`rbac_execution.py` adds an entry-owned `SharedExecutionGuard`, not an enabled
tool or a replacement conversation route. Trusted server code provides the original
HA Context, paired `PreparedRequest` and administrator-owned restricted kiosk set.
It must reuse the ledger for the entry lifetime and close it on unload/reconfiguration.
Constructing a PreparedRequest manually is not authentication; transport provenance
and admission of freshly verified turns remain mandatory before this is wired up.

`prepare()` seals a proposal containing one on/off operation and 1–32 distinct exact
light/fan IDs, bound to that caller object, user ID, prepared turn and entity registry
identity. Proposals expire after 30 seconds. Only one proposal may be issued per
prepared turn; the bounded 256-turn ledger fails closed instead of evicting active
replay protection. Copies/manual proposals, switched callers/turns, reused tokens,
unapproved kiosks and unknown speakers cannot execute. A proposal is not a cached grant.

`async_execute()` consumes the proposal before its first await, checks the whole
batch, then rechecks **both** current RBAC policies and native read/control rights
inside every native execution task. After policy/account awaits it synchronously
revalidates caller binding, expiry, registry identity, exposure and current state.
Unregistered/disabled/replaced entities, group/template platforms, member metadata
(even empty), unavailable states, indirect domains and arbitrary operations are denied.
The RBAC oracle also denies control when either actor hides state or identity.

The adapter uses HA's `ServiceIntentHandler.async_call_service` exact-entity
construction with a request-local facade. Its only service admission accepts the
sealed domain/operation/one entity ID and the unchanged Context, with a final policy
check before forwarding to HA. It is not an arbitrary service-call bridge, global
handler patch or preflight followed by unrestricted name/area resolution. The native
handler's background timeout is overridden to await its child task; cancellation
propagates and no action is retried. Unsupported argument broadening or a native
handler returning without admission cannot report success.

The boundary is HA service admission, not physical hardware completion. An integration
can await or queue device I/O after admission; already-admitted work is not retractable.
Revocation between targets stops the remainder and reports partial completion. An
execution error is unconfirmed, never a reason to retry. There is no batch rollback,
system-wide permission lock or policy enforcement inside third-party device firmware.

Native-first and model paths can share this exact-ID boundary, but neither is wired
to it yet. Protected name/alias/area resolution, native LLM tool presentation, safe
result/readback handling and client ingress remain gates. The model envelope still
has `tools=[]`; do not route checked text back through unrestricted native IntentTool.

## Connected dormant ingress prototype

RBAC's new `assist_ingress.py` is **not** its Supervisor add-on `ingress.py`.
`ProtectedAssistIngress` is an explicitly constructed, in-process registry; nothing
in HA setup, the proxy, HTTP, WebSocket, conversation or pipeline handling imports or
registers it. Its version-1 handshake binds a trusted provider to an explicit kiosk
set and server-held source capability objects. It does not authenticate a browser,
discover a satellite, confer authority on arbitrary Python code or grant any proxy
route exception. An actual authenticated transport/source adapter is still required.

The prototype connects these components without enabling a live route:

1. Trusted server code supplies the original authenticated HA Context and a source
   capability established outside client JSON. `admit()` seals that caller, exact
   provider registration and owning pipeline task in an expiring admission.
2. `async_dispatch()` consumes admission before awaiting anything. Copies, forged
   admissions, wrong-task use, missing registrations, unapproved kiosks/source objects,
   expiry and capacity exhaustion are denied. Registrations cannot silently replace
   each other; teardown invalidates leases and a closed registry cannot reopen.
3. Codex's entry-owned `rbac_dispatch.ProtectedDispatcher` consumes the exact private
   clean-transcript handoff from its existing SpeakerRuntime, then verifies the packet
   using the current server-owned pairing key and shared nonce cache. Raw packets,
   serialized transcripts, manually supplied PreparedRequests, unknown/unbound voices
   and STT evidence belonging to another task are not accepted.
4. The dispatcher accepts **only** a structured exact-ID on/off command. Caller,
   speaker, device, history, instructions and service-selection fields cannot be
   supplied in that command. It freezes operation/targets before policy awaits, checks
   a server-configured bounded candidate set, and rebuilds both actors' filtered
   readable context. Every requested target must survive projection; a mixed batch
   cannot silently drop forbidden devices and execute the rest.
5. The sealed command then enters the existing native execution guard. A new
   request-liveness callback revalidates registration, caller, admission lifetime and
   pairing-key digest after policy awaits and at every service admission. Either
   policy or native permission revocation is independently rechecked by RBAC.
6. Results contain only fixed status and completed-command count, never raw context,
   denied entity names, policy detail or exceptions. Teardown closes the guard before
   cancelling active parent pipelines; cancellation propagates to awaited native work.

No model call or tool has been enabled. This command prototype does **not** resolve
free text, names, aliases or areas, and does not perform authenticated network login.
It expects an exact proposal from a future protected native/model resolver; it never
forwards a denial to ordinary Assist. The context/envelope builder remains tools-free.
Existing speaker/account matching on ordinary conversation paths is unchanged.

Registration is trusted integration coordination, not an authorization sandbox or
proof that a self-declared provider is safe. A future route exception must be reviewed
against its actual transport authentication, provenance, dispatch and response behavior.
The embedding integration must keep one runtime/dispatcher per entry, close on pairing
or configuration revisions, and await cancelled pipeline tasks during teardown. No
production lifecycle wiring has been added. Already-admitted integration/device I/O
still cannot be retracted; the service-admission limits above continue to apply.

## Required before activation

### Intended clients identified by the owner

- [Fully Kiosk Browser](https://www.fully-kiosk.com/): use the authenticated HA
  browser session as the tablet caller. A personal tablet can use its person's
  account; a shared kiosk needs an explicitly restricted device account/ceiling.
  Fully's lockdown is not backend authorization. Verify that microphone capture
  reaches HA Assist and the paired Voice Match STT path; Android/text-only speech
  recognition must not be treated as a verified fingerprint or a satellite claim.
  Browser microphone permissions, WebView support and secure context require testing.
- [echo-dot-assist](https://github.com/Gamer92000/echo-dot-assist): its current
  documentation describes `hassmic` presenting as an ESPHome device by default,
  with Wyoming mode as an alternative. Target the ESPHome-compatible HA voice
  path first, alongside future ESPHome devices. This is not the normal Alexa
  cloud skill path. No Echo flashing/firmware change is authorized by this work.
- Shared hardware identity must come from a trusted server-side device/connection
  binding. A browser-supplied `device_id`, pipeline selection or model argument is
  not proof that the caller is that satellite. ESPHome versus Wyoming provenance
  must be verified separately; supporting one does not establish the other.

The owner confirmed shared household Fully tablets: kitchen first, living room
later. Plan separate restricted kiosk accounts and explicit administrator opt-in
for each. A voice policy preflight intersects the paired speaker's account with
the authenticated kiosk account as ceiling, without replacing HA Context. There
is no enabled kiosk account list or automatic policy assignment. Dashboard/touch
actions remain the kiosk account's RBAC responsibility; recognizing a voice does
not log the browser into that person's account or unlock personal data on-screen.
The development preflight denies unknown/neutral/legacy or client-dictionary voice
claims and unapproved/default kiosk accounts. It is not a transport/execution grant.

No actual
satellites were found in the bounded `assist_satellite` entity query at inspection;
that does not establish absence of all voice hardware or future devices. None of
these client paths has passed protected end-to-end acceptance yet.

### Remaining gates

1. Implement and review actual authenticated tablet/satellite transport and trusted
   source bindings around the dormant registration/admission prototype. Only a
   destination with verified end-to-end enforcement may receive a narrow ingress
   exception. Keep ordinary conversation/Assist routes denied, even when registered.
2. Connect a protected resolver/model caller to the implemented context/command
   dispatcher. Registry metadata, history and tool-result ingestion remain unsupported
   and must stay excluded until separately guarded. Unrestricted live-context prompts
   are unsafe; this prototype accepts exact structured commands, not free speech.
3. Connect **every** native-first/model action through protected alias/area/multi-target
   resolution and the guarded dispatcher, with restricted result handling. No ordinary
   conversation/native LLM dispatch has been wired into it. Delayed actions remain
   unsupported; do not forward free text or add a raw service-call escape hatch.
4. Explicit administrator selection of shared satellites and a low-risk ceiling.
   Verified paired voice/profile ownership may only narrow that ceiling; it must
   not replace HA Context, grant administrator rights or restore another speaker's
   confidential history. Missing/uncertain/replayed metadata denies restricted tools.
5. Account/policy-bound concurrent history handling, restrictive readback, default
   denial of unclassified tools/indirect actions, minimal redacted denials and an
   administrator review UI. No MCP or AI Task permission inheritance is implied.
6. Cross-project native tests covering permitted/forbidden devices, filtered context,
   every ingress/dispatch path, role revocation, unknown speakers, prompt injection,
   account switching, concurrency, reload and unavailable policy. Follow with explicit
   owner acceptance on both a tablet and each approved satellite.

No claim of system-wide enforcement: other integrations and pre-existing automations
can act outside this protected path. Even an allowed light may trigger an unrelated
automation. Voice biometrics are fallible and cannot authorize high-risk actions.

## Initial evidence

Twenty Codex adapter tests passed, including separate shared kiosk ceilings and
denial of missing/uncertain/unbound/client-supplied voice claims. These are preflight
contracts, not proof of protected transport or execution. The RBAC checkout's oracle tests plus existing
intent-surface denial regressions passed 33 cases; expanding to policy, schedule and
location regressions passed 121 cases on the current local HA environment.
These establish the foundation only; they do not establish tablet/satellite access,
real acoustic recognition, end-to-end protected execution or live permissions.

The context stage passed 22 new consumer/envelope tests (42 with the policy adapter),
and the full Codex fast suite passed 1,055 tests plus 32 subtests. The RBAC oracle,
projection and policy/intent/schedule/location selection passed 132 tests, including
two real cross-checkout contracts linking paired packet preparation, both RBAC role
compilers, the Codex snapshot builder and tools-disabled model envelope. No cases
were skipped in that run. Changed-file Ruff passed in both checkouts. Full native
Codex suites and all RBAC tests were not rerun; these are development contract tests,
not transport, model-provider, device or deployed parental-control acceptance.
Focused existing Codex native voice/MCP/history regressions passed 12 tests on the
current HA environment and 3 on the minimum environment (1 unsupported feature skip).
The distribution projection passed with 63 files. None of these checks enables access.

The subsequent exact-target stage passed 43 new native cases on current and minimum
HA. With existing voice/MCP/history regressions, the focused selections passed 55
on current HA and 46 on minimum HA (one unsupported-feature skip). The selected RBAC
run passed 140 on each environment, including eight new real cross-checkout execution
contracts. The fast suite remained 1,055 plus 32 subtests, and distribution projection
passed with 64 files. These do not establish client routing, acoustic accuracy,
physical-device completion or a full native/RBAC-suite pass. No live code, policy,
tools or ingress exception was enabled.

The subsequent dormant ingress stage added 51 cases in `ha-rbac/tests/test_assist_ingress.py`.
The selected cross-checkout ingress/oracle/policy/intent/schedule/location selection
passed 191 on current and minimum HA, without skips when both checkouts were loaded.
These use real paired handoff/nonce preparation, compiled roles, filtered context and
native synthetic service handling, but simulate already-authenticated Context/source
admission. They do not test network login, real STT audio, device enrollment or live
tablet/satellite routing. The full Codex fast suite remained 1,055 plus 32 subtests.
Focused native regressions passed 55 on current HA and 46 on minimum HA (one
unsupported-feature skip); distribution projection passed with 65 files. Changed-file
Ruff passed. The handoff checkpoint subsequently fixed the unrelated formatting-only
E501 and passed full-repository Ruff. No live route, provider registration, installed
code or policy changed.
