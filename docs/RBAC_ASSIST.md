# RBAC-protected Assist development

## Status: inactive protected-path development, not working parental controls

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
