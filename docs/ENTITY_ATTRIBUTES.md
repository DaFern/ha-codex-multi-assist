# Read-only entity attributes

This experimental feature contributes `codex_assist__GetEntityAttributes` through
Home Assistant's native `llm.py` provider platform. It supplements, rather than
patching, HA's deliberately reduced `GetLiveContext` attribute list.

## Agents and availability

The provider is selected by the Codex request platform and Assist API, not an
agent ID, personality name, starter-profile list or agent count. Every configured
Codex conversation profile can receive it, including profiles added later. It
does not impose a four-agent limit or automatically enable the tool in unrelated
conversation integrations, AI Task or other LLM APIs.

Native provider discovery requires **HA 2026.8+**. HA 2026.6 remains supported for
existing Codex functionality but does not load this feature. No private API patch,
legacy injection or raised global minimum is introduced. Local native tests were
run on 2026.10.0; intermediate 2026.8/2026.9 releases are not claimed locally tested.
The provider adapts legacy dictionary results/schema APIs and current ToolResult
and read-only annotations using the corresponding HA capabilities.

## Read contract

The model supplies an exposed entity's name or alias, one to eight attribute
names, and optional domain/area filters. HA's native matcher must identify exactly
one accessible entity; ambiguity asks for clarification rather than choosing one.
The tool never accepts a service, template, file path or arbitrary expression.

The result contains the matched entity ID, only the requested approved values,
units where known, and separate `missing` and `withheld` lists. Zero is a reading,
not a missing value. Unknown/unavailable entity states are errors, even if stale
attributes remain attached. Absent weather units are not guessed. Climate/water
heater temperatures use HA's configured temperature unit. Standard percentage,
duration and Kelvin attributes retain their defined units; raw light brightness
and media volume retain their native numeric scales, not invented percentages.

There is no unrestricted attribute dump. Common fields are `device_class` and
`unit_of_measurement`. The reviewed domain-specific set includes:

| Domain | Supported details |
| --- | --- |
| Weather | Temperature/apparent temperature/dew point, humidity, pressure, wind speed/gust/bearing, visibility, ozone, clouds, UV and associated units |
| Climate | Current/target temperatures, temperature limits/step, humidity, HVAC action/modes, fan/preset/swing modes |
| Water heater | Current/target temperatures, limits, operation/away modes |
| Humidifier | Current/target humidity, limits, available/current modes |
| Light | Brightness, colour modes, Kelvin limits/temperature, RGB/HS colour, effects |
| Fan | Percentage/step, presets, oscillation, direction |
| Cover | Current position and tilt position |
| Media player | Volume/mute, title/artist/album/type, duration/position, source/sound mode, shuffle/repeat |
| Vacuum | Battery level and fan speeds |
| Lock | Battery level when actually provided as an attribute |
| Sensor | State class and battery level when provided as an attribute |
| Switch | Legacy current power/current attributes and battery level when provided |

The exact key allowlist is in `entity_attributes.py`. Attribute support does not
guarantee an integration supplies that attribute. Battery/power values exposed as
separate sensor entity states remain available through ordinary HA live context.
Forecast arrays, history, credentials, URLs, images, arbitrary custom keys and
nested objects are not added. Custom fields need explicit review and tests.
Strings, scalar lists and numeric values are bounded; unsafe/oversized values are
withheld rather than stringified or silently truncated.

## Authority and privacy

Every call rechecks exposure and the original user's applicable HA read permissions,
even when its API instance was prepared before exposure changed. Deleted/inactive
users are denied. A missing request Context is denied. A real HA Context without
a user ID retains HA's internal/local-pipeline semantics and is still restricted
to exposed entities; no administrator or other household identity is substituted.
Speaker recognition does not grant authority. The tool does not read configuration
files, internal storage, credentials or unexposed entity attributes.

Candidates are filtered before matching. An empty authorised list returns an
error without invoking HA's matcher, whose empty-list behaviour otherwise searches
all states. The matched ID is checked against the authorised set as well. Hidden,
denied and nonexistent targets share a generic response, without leaking readings.

The tool calls no services and makes no state changes. Read-only annotations and
legacy query-result typing keep it on the query-answer path, not the action-success
acknowledgement path. Returned text is model data, not trusted instructions. Values
are returned through normal HA tool/chat history to the configured model; this is
not a new confidential channel and no extra raw-value logging is introduced.

## Verification and deployment boundary

Fast projection tests cover domain-specific allowlists, units, zero/null/missing
values, large/nonfinite values, nested objects, bounds and defensive list copying.
Native tests cover actual provider discovery/schema conversion/API dispatch,
cross-domain reads, aliases/ambiguity, exposure revocation, denied/deleted/inactive
callers, unavailable states, context/API isolation and no service calls. Scripted
conversation delivery exercises eight saved agents and a newly added ninth profile.

The complete checkout, including shared personality-aware action replies, passed
916 fast tests plus 32 subtests and 583 native tests on HA 2026.10.0 (1 skipped).
The minimum HA 2026.6.0 lane passed 363 tests with 193 skips, including the unsupported
native-provider module. Ruff, the 56-file distribution projection and whitespace
checks also passed. These are local synthetic results, not a published release or
proof of actual model/device behaviour.

Synthetic model replies establish tool wiring, not that every live model phrase
will select the tool or faithfully speak its result. Installed runtime sources/assets
match the tested checkout; recovery after the approved Core restart is verified.
No device command or live attribute query was issued as part of that verification.
Live-model selection/wording and broader device acceptance remain pending. No Core
patch, sensor duplication or release is implied.
