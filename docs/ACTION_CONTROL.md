# Shared smart-home action handling

The same conversation owner handles every managed personality. Device control is
not selected by an English verb regex, a light-only guard or a household-specific
entity list. The shared action handler and personality replies are installed on the
test system. Startup recovery is verified; real-model/device acceptance of the new
full-personality wording remains pending. This is not a published release.

## Native-first control

After verified speaker automations and HA prompt/API preparation, the integration
asks the built-in Home Assistant agent's `async_recognize_intent` to recognise the
original request, restricted to exposed entities. Recognition does not execute a
command. Native language sentences, names, aliases, areas and capabilities remain
owned by HA, rather than being reimplemented in this integration.

A recognised intent is matched only to a real native `IntentTool` already present
in the request's Assist LLM API, including namespaces and older HA's dispatch-name
contract. Only slots admitted by that tool's published parameter schema are
forwarded. An explicit array schema can wrap a scalar native slot. HA performs
normal tool validation and execution through `ChatLog.async_add_assistant_content`.
The existing LLM context retains the original caller and exposure/permission
restrictions. There is no arbitrary service-call bridge, administrator substitute,
recursive conversation call, broader API fallback or device-command retry.

Native device controls execute before any model acknowledgement. This prevents an
initial text-only model success from replacing a recognised command. Afterwards,
the shared reply step uses the selected profile's instructions, including any
user-created personality, with tools and hosted search disabled. The device action
is not repeated and the model does not choose whether it succeeded.

Unrecognised sentences, unsupported native intents and intents without an available
authorised tool retain the model path. This is all-domain native routing, **not a
universal natural-language classifier** or a guarantee that every possible phrase
is recognised. Model-generated general answers are not independently verified for
truth. Unsupported/free-form requests still require appropriate clarification and
an actual tool result before relying on any device-action claim. AI Task and
configured speaker-automation response handling are unchanged.

## Shared result handling

For both native-first and model-requested tools, the integration checks only this
round's call/result pairs. Missing or duplicate results are unconfirmed. Errors,
explicit failures, empty native action acknowledgements and partial successes do
not become model-written success messages. Legacy dictionaries and current
`ToolResult` wrappers are supported.

Native `action_done` results require nonempty successes and no failed targets.
New-style generic tool success acknowledges execution through the typed native
protocol; legacy generic tools need an explicit success flag. Read/query results
are distinguished using native response types and tool read-only capabilities,
with a class-checked adapter for the older HA live-context tool.

The replies distinguish accepted, failed, partial and unconfirmed requests. They
do **not** turn an acknowledgement into a physical postcondition: a cover may be
moving, a thermostat may be adjusting, and a scene or script may still be running.
The generic acknowledgement is “Home Assistant accepted that request”, never a
fabricated “the lights are off” or “the door is locked”. Device state/readback can
be requested separately. Partial/failed/unconfirmed actions are never replayed to
obtain a nicer reply. Action processing stops after the result. A separate speech-
only step can add personality, but cannot execute a completed action again.

## Personality-aware acknowledgements

The tools-disabled step receives a fixed outcome category and factual sentence,
plus an optional sanitized summary containing only the recognized operation and an
allow-listed target domain (for example, `turn_off` and `light`). It receives no
entity name/ID, raw tool arguments, tool response, exception string or user
command/history. The summary is context, not evidence of device state. Its system
instructions use the current selected agent's rendered prompt and optional verified
Voice Match name/preferences, never a hard-coded character or another agent's prompt.
The model writes the entire reply in that personality and the requested language;
there is no mandatory stock sentence, prefix or suffix. The outcome explanation is
input evidence, not a required spoken template. Instructions require preserving
accepted, failed, partial and unconfirmed distinctions without inventing physical
completion or treating partial/uncertain handling as full success.

The structured result must carry the same outcome category, only the allowed fields,
a bounded reply and no other category's factual sentence. Unexpected tool calls,
incomplete/invalid responses, excessive size, errors and a 15-second generation
deadline fall back to the existing factual sentence. Responses are buffered until
validated, and the stream is closed on every exit. Cancellation propagates. There
is no speech-generation retry or extra tool execution. Authentication failure after
a native action preserves its known result rather than reporting that action failed.
Provider/authentication outages themselves still use local generic error guidance.

This adds one model request and latency for action acknowledgements. The generation
timeout excludes the existing credential resolution step. No model-native state
from this isolated reply is retained; the final delivered speech joins normal HA
history. Outcome category/schema checks are structural, not semantic proof that
free-form prose is truthful. Live acceptance must check the selected model follows
the factual constraints while using each agent's personality. No semantic guarantee
is made by the model's echoed category alone.

HA local intents that run before this integration still use HA's own responses.
This feature does not silently change pipeline settings, affect unrelated agents,
alter the installation's temperature-response override or change AI Task/learning.

Model response rounds are buffered to completion before any tool batch is
dispatched. Pre-tool speech is dropped when a tool handoff exists. No-tool answers
and clarification questions are retained. This can delay first speech for ordinary
model answers until their response completes. Incomplete streams release neither
buffered speech nor actions. Buffering does not widen the existing auth-retry
window: once text/calls have been received, a late auth failure is not retried.
Private provider replay state and action/result history remain paired.

## Verification boundary

Fast tests exercise shared evidence handling across fourteen entity domains,
legacy/wrapped results, read-only capabilities, partial/failing/missing outcomes,
native slot admission and caller-input identity. Native HA tests use real language
recognition, exposed entities, native intent tools, ChatLog and registered services
for lights, switches, fans, locks, covers, climate, media players, scenes and
scripts, through all four starter agents and an independently configured custom
agent. Both successful and failed services execute exactly once before the
tools-disabled personality request. Alias-only groups without area
assignment and unchanged caller identity are covered separately, as is rejection
of unexposed targets in both routes.

The complete source checkout passed 916 fast tests plus 32 subtests,
583 native tests on HA 2026.10.0 (1 skipped), and 363 native tests on the
minimum HA 2026.6.0 (193 skipped). Ruff and the distribution projection check
also passed. These are local synthetic results, not remote CI or release evidence;
skipped tests do not establish compatibility for the features they omit.

Domain fixtures wait for HA's deferred intent registration before issuing their
first request. Clarification tests separately cover a complete native command
and a model-requested tool after an unrecognised bare-target reply. Older HA does
not necessarily recognise an abbreviated reply such as “Test alpha” as a command;
no custom continuation parser or action retry is added to compensate.

Services, entities, identities and model responses in these tests are synthetic.
Passing them is not physical-device acceptance or proof of model compliance for
unsupported/free-form wording. The approved deployment replaced only the two
runtime files differing from the installed baseline; all 56 runtime sources/assets
matched the candidate on read-back. HA configuration validation passed. Following
the approved Core restart and a wait of at least 60 seconds, assistant/learning/STT
entities returned and Supervisor was healthy. No live device command was issued.
No release or beta qualification is implied by this installation evidence.
