# Protected satellite timers — development only

This change is not installed or physically verified. Installation and a Home
Assistant restart require separate approval. Ordinary conversation and the
alarm-clock integration are unchanged.

## Commands

On an enrolled, timer-capable ESPHome satellite:

- “Set a timer for ten minutes.”
- “Set a pasta timer for twelve minutes.”
- “Cancel my timer.”
- “Cancel the pasta timer.”
- “Cancel the ten-minute timer.”
- “How long is left on the pasta timer?”
- “List my timers.”
- “Pause the pasta timer.” / “Resume the pasta timer.”
- “Add two minutes to the pasta timer.”
- “Take thirty seconds off the pasta timer.”
- “Cancel all timers.” (this satellite)
- “Stop the timer that is going off.” (one permitted reported alert)
- “Cancel the pasta timer in the kitchen.”

If several timers match, the assistant must ask for a satellite, name or starting
duration before acting. Adjustment amounts and starting-duration selectors are
separate fields; adding time does not change how the original duration selects it.
Timers on this satellite are shared by its currently admitted speakers, including
its configured guest role; they do not belong to a remembered voice identity.

Local controls remain available without the optional remote capability.
Cross-satellite operations are **cancel/stop/cancel-all only**: no remote start,
pause, resume or adjustment. An explicitly named satellite/room must resolve to
one permitted enrolled target. It never falls back to this satellite.
An explicit remote destination must match a permitted declared alias actually
present in the current utterance, not a model-selected destination from history.
Remote timer-name selectors must likewise be named in that utterance; the
conservative duration-selector check recognises English hour/minute/second forms.
After an ambiguous result, the tool requires a fresh user reply before another
mutation: a second model proposal cannot silently pick one of the choices.

Cancel-all stays local by default. An explicit satellite name can target its
timers. Bulk `scope=all_permitted` additionally requires a same-turn broad request,
such as “cancel all timers everywhere” or “on all permitted satellites”. A model
flag, previous request or remembered “yes” is insufficient. The conservative
broad-scope veto recognises English forms; use one explicit satellite name for
other languages or narrower subsets. Negated/except/only wording does not grant
whole-house scope. No new household permissions are assigned automatically.

## Countdown and ringing

The tool uses Home Assistant's existing intent `TimerManager` and the satellite's
registered native timer-event handler. It does not create timer helpers, use
Music Assistant or schedule a device command. The existing ESPHome firmware
receives start/cancel/finish events and owns the display and ringing.

For Kiosk Satellite, `satellite_timer_targets.py` reads the device's actual
`vs_list_timers` response. Its `finished` flag reports an outstanding timer alert;
zero seconds remaining alone is not ringing evidence. A muted or auto-silenced
alert can still be outstanding, so this does not prove audible sound.

“Stop the timer” checks every permitted supported enrolled target and selects
only one positive alert. Several matches require clarification. An authorised
target with no reporting capability, or a failed query, prevents automatic
guessing; name one satellite instead. A device's separate alarm-clock ringing
sensor is never used as timer evidence.

Outstanding alerts use the exact `vs_cancel_timer` native ESPHome action on the
same runtime, then are queried again. Only disappearance from the reported list
permits “Cancelled”; failed/unchanged read-back is reported as unconfirmed/partial.
Running timers use Core's exact timer ID, not firmware name matching or global
native intent fallback. This also avoids accidentally matching another device's
similarly named timer.

For ordinary ESPHome devices without that Kiosk capability, Core removes completed
timers from its active list. A bounded in-memory journal
retains the original timer object so a later cancel can send a native CANCELLED
event for that ended timer. This is reported as **“Sent a dismissal request”**, not
proof that the alarm became silent. Firmware must handle that event appropriately;
some firmware instead dismisses ringing on wake word or through its own local
controls. Actual display, expiry, ringing and dismissal must be checked on the
device before this feature is accepted. No firmware modification is included.

Ended records expire after one hour and are ignored after native handler
replacement. Running timers and the journal are not persisted across a Home
Assistant restart. This is not a replacement for a safety-critical timer.

## Boundaries

- The tool exists only inside a live protected voice admission and only when the
  registry identifies an enabled ESPHome satellite with a native timer handler.
- Local device identity comes from the admission's registered satellite. Remote
  candidates come only from the Codex entry's current protected-satellite enrollment,
  then are filtered by the paired RBAC timer oracle, never LAN discovery or a
  model-supplied device ID, URL or service.
- Fresh source/caller/role/key/expiry checks, native handler/manager and registry
  identity checks, and existing projection validation precede every effect.
- Matching is restricted to authorised exact devices **before** selecting a timer. Core's
  global/floor/area fallback matching is deliberately not used.
- Delayed conversation-command timers are never created, read or cancelled.
- No synthetic user, general Assist discovery, raw service bridge, household
  policy edit or timer-handler/subscription replacement is introduced.
- The existing non-empty permitted household projection must remain valid before
  each timer action, including its native/RBAC account, role and schedule checks.
  No metadata-only role selector is treated as an execution grant. Timer-only
  roles with no readable household entities are not enabled by this first change.
- Remote metadata/read-back requires exposure and native/RBAC read permission for
  the target `assist_satellite`; cancellation additionally requires native/RBAC
  control and the open-tier `timer.cancel` check. Hidden timer/name/area fields
  fail closed. This separate `TIMER_POLICY_VERSION=1` API does not relax baseline
  Assist/pipeline/service denials. Older/missing providers grant no remote control.
- Remote target labels, aliases, registry identity and capability fingerprints
  participate in history visibility dependencies and are rechecked after model
  awaits. Timer names from another device cannot enter an unrelated local-only
  saved dialogue projection.
- The catalogue receives one final batched read check, then metadata is rebound
  synchronously. Timer-bearing model rounds revalidate the full frame immediately
  before provider requests, not just before actions or final speech.
- Remote bindings pin the entity, configuration runtime, encrypted connected
  client, timer handler and the two exact native action definitions. Replacement,
  disconnection, changed commands or changed enrollment revoke the turn.
- Durations are positive whole seconds, up to seven days. Names are bounded
  printable text; selection must be unique. There are at most 32 local
  active/retained choices and 1,024 retained records across the instance.
- Request-local effect ledgers and action budgets prevent repeated effects.
  A native callback error is uncertain and is never retried automatically.

## Verification before deployment

`tests_ha/test_satellite_timers.py` exercises actual Core timer objects and
registries, simulated transport event delivery and guest/matched authorization.
It checks target isolation, ambiguous/duplicate names, duration selection,
revocation, replacement, replay, invalid arguments, delayed-command exclusion,
finished-event dismissal, remaining time, pause/resume, adjustments, cancel-all,
scope veto, capacity and deterministic spoken feedback.

`test_satellite_timer_targets.py` adds simulated native ESPHome action/client
boundaries with real Core timers and registries. It checks positive/ambiguous
alerts, read-only targets, unknown/failed reporters, exact IDs, read-back,
malformed device data, replacements, enrollment and history visibility.

The optional `tests_ha/test_satellite_timer_admission.py` pairs the actual RBAC
admission, private STT handoff and compiled policy with native timers. It covers
guest/matched start and cancel across fresh turns, post-prompt source/key/role/
account/read-permission revocation, serialized-transcript denial and held-tool
expiry. It also drives real guest/matched cross-target permissions through the
protected model loop and checks revocation after the model prompt. It requires
the paired RBAC source to be importable; standalone runs skip it.

These are not physical satellite, external model or microphone acceptance tests.
After separately approved installation/restart, supervise a short countdown,
cancel it while running, then let a second countdown finish and dismiss it.
Also test two named timers and an ambiguous cancel without changing either timer.
For cross-satellite acceptance, use two separately enrolled/permissioned kiosks:
let one ring, stop it from the other, then test two simultaneous alerts and a
read-only guest. The currently observed installation has only one Assist satellite,
so a physical two-satellite result has not been established.
