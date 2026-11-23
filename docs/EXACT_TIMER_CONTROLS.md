# Exact-ID kiosk touch controls — local development

This is a paired development change, not a released feature.
It requires modern satellite support (HA 2026.10+), the matching RBAC provider,
an enrolled timer-capable ESPHome satellite and a compatible kiosk client.
Deployment and restart require separate owner approval. No household permission
changes are included.

## Protocol

The authenticated HA route is `/api/codex_assist/timers/v1`.
Every application response identifies `api="codex_assist.exact_timers"` and
integer `version=1`, with `Cache-Control: no-store`.

- `GET` returns `actions`, a 48-hex-character `nonce` and `expires_in=30`.
  It returns no timer, satellite or household metadata.
- `POST` accepts exactly `entity_id`, `timer_id`, `action`, `nonce`, plus a
  positive integer `seconds` for `add` or `remove` only. Actions are `pause`,
  `resume`, `cancel`, `add` and `remove`. Adjustment amounts and resulting
  increases are bounded to seven days.
- `entity_id` must identify an enrolled `assist_satellite.*`. This standard
  resource key also lets the existing RBAC HTTP proxy evaluate the exact target.
- Success means `status="accepted"` with the same `timer_id` and `action`.
  It confirms Core accepted the operation, not physical display or sound.

The route is registered alongside the modern protected satellite adapter.
Unloading removes its enrollment, not the route: an unavailable companion returns
503 rather than becoming an absent endpoint that might invite legacy fallback.

## Authority and replay

Home Assistant authenticates the bearer token. The active, non-system HA account
is the only subject: no supplied speaker ID, guest-role override or Voice Match
substitution is accepted. The separate additive
`TIMER_CONTROL_POLICY_VERSION=1` contract requires fresh native/RBAC read and
control, conversation exposure, visible timer metadata, target availability,
native handler support and the specific `timer.<action>` tier.
The existing voice `TIMER_POLICY_VERSION=1` vocabulary is unchanged.

Nonces are volatile, short-lived, account-bound and single-use; storage is bounded.
The nonce is consumed before awaiting policy, including for denied/unconfirmed
mutations. It is not a retry token or an independent grant.
After policy, the route synchronously rechecks the unique loaded enrollment,
options, registry, manager, handler and exact timer object before the effect.
Timers on other devices and delayed conversation-command timers are rejected.
No start, bulk cancellation, general service call or name/duration lookup exists
in this endpoint. Identical named or unnamed timers remain independent objects.

## Kiosk compatibility

The local client uses its configured HA URL/token and the exact timer ID already
received through native events. It sends no name or duration selector. Redirects
and automatic retries are disabled. A denial, timeout, malformed response,
unknown version or unconfirmed mutation never falls back to native intents.
An initial discovery 404, before any POST, can retain stock-HA compatibility;
known identical timers are refused on that legacy path. Once an endpoint responds
or fails other than this initial absence, that URL is latched against downgrade
for the client's lifetime. This latch is not persisted across app restarts.
Finished ringing-timer dismissal remains the kiosk's existing local operation.

## Verification and release limits

Tests use real isolated HA HTTP authentication, registries and native timer
objects, with simulated external device callbacks. The paired case additionally
uses the real RBAC catalog, decider and evaluator. Standalone Dart tests verify
the HTTP client protocol, not `VoiceManager` or a full Flutter application.

Before acceptance, separately build/analyze/test the complete Flutter app and
test identical named and unnamed timers on hardware: pause/resume, both time
adjustments and cancellation must change only the selected timer. Also check
expiry/ringing, permission revocation, missing companion, disconnects and
unconfirmed responses without automatic retries. Deployment and any restart
need separate approval.

The Kiosk Satellite fork is <https://github.com/DaFern/kiosk-satellite>.
Upstream's CC BY-NC-ND licence restricts distribution of adaptations; modified
kiosk source/builds must not be pushed to that public fork or published without
maintainer permission. The owner approved retaining the adaptation in a separate,
private, non-commercial repository; the public fork remains unmodified. Private
storage does not grant permission for redistribution or commercial use.
The independent-plugin exception does not authorise modified-app distribution.
This protocol document includes no kiosk implementation code.
