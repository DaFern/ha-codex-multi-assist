# Voice Match and optional per-person response preferences

The experimental connector pairs **Codex Multi Assist 0.7.0** with the **Voice Match
0.4.7** app. Record exact source revisions too. It offers one everyday **Voice Match**
STT choice on **HA 2026.10+**, clean chat text, recognised names and optional personal
instructions. **Voice Learning** is a separate entry/assistant and uses a separate key.

## Setup

1. Install compatible reviewed components together; packet v2 requires both sides.
   Back up before replacement. Integration Python updates require an approved Core
   restart; app builds/updates are separate.
2. Enrol voices and assign each to its actual HA account. Personal instructions in
   Manage voices are optional; an empty value still permits recognised-name context.
3. In the app's **Administrator settings → Voice Match connection**, create a
   personalisation key only if needed and enable the endpoint. Never put keys in
   chat, logs, URLs, screenshots or issues; retain an existing working key.
4. On the Codex entry choose **Configure → Voice Match**. Enable it and enter the
   internal hostname, **10352** and the same personalisation key. Blank preserves
   a saved key; disabling removes it. The initial enabled toggle does not activate
   anything until valid setup is saved; saved opt-outs remain off.
5. Select **Voice Match** STT, a Codex agent from that same entry and usual TTS in
   an approved test assistant. No separate Wyoming STT connection is needed. Disable
   local-first handling if offered and avoid native sentence-trigger conflicts.
6. Test multiple people/devices, uncertainty and rollback. Keep ordinary Whisper
   available. Do not pair this STT with an unrelated or intent-only agent.

Setup probes service metadata, not audio or key validity; every transcription packet
is verified separately. The stable existing entity ID/pipeline binding is retained
(`stt.clean_voice_messages` on the test installation), displayed as **Voice Match**.
Saving options reloads the entry, not pipelines. No old-source review/removal menu
exists and no redundant connections are automatically deleted.

## Names, preferences and permissions

A confidently matched assigned profile supplies its display name, including when
instructions are empty. Names are literal data, limited to 80 printable characters;
they are not inferred from presence or phone login. The model receives the name on
normal/tool/auth-retry composition and is guided to acknowledge recognition naturally.
Its wording and real acoustic accuracy are not guaranteed.

Personal instructions are literal text up to 2000 characters, added after rendering
the agent's base prompt—not executed as Jinja. Name and preferences go to the selected
provider. Never store secrets or sensitive facts. Packet v2 also carries the enrolled
profile's assigned HA user ID encrypted; Codex accepts account-bound voice context only
when that ID matches the active HA caller. HA `Context` is never replaced or impersonated.
An unassigned/neutral profile, legacy v1 packet, inactive/system account, or caller
mismatch fails closed: no profile name/preferences/history, speaker automation, native
HA controls, or MCP tools are used. Ordinary model chat may continue without HA tools.
For a match, the caller retains only their normal HA permissions; MCP remains
administrator-only and read-only. Voice is not a login or sensitive-action approval.

## Transport and conversation scope

The app's stricter similarity/gap checks use an independent assessment of the PCM
sent to Whisper. Incomplete/conflicting assessments stay neutral; acoustic rejection
still returns no transcript. The paired endpoint uses Fernet authenticated encrypted,
utterance-bound context. Wrong key, expiry, altered text and replay fail closed.
The direct STT adapter returns clean words and holds the packet privately for the
exact pipeline task; [handoff design and limitations](CLEAN_SPEAKER_STT_PROTOTYPE.md).
A stock personalised-Wyoming path still displays the encrypted header in chat.

Active model scope is bounded by speaker/revision/name and agent within the supplied
HA conversation. Speaker/agent changes, preferences/ownership changes, uncertainty,
idle expiry or restart reset it. Returning speakers do not recover an old branch;
no history is fetched by recognised identity. Later concurrent turns are excluded.
HA's normal log retention is not erased or converted into authenticated private logs.

Unpaired ordinary requests retain the ordinary path. Enabling pairing starts a new
scope, including plain requests; disabling retains isolation for that running entry's
lifetime. Core restart clears volatile scopes and in-memory conversation logs.
Scope-specific provider cache/session IDs may increase token cost/latency; live
costs are unmeasured.

The bounded entry-scoped replay cache survives ordinary entry reload but not Core
restart. Payloads expire after 120 seconds with Fernet clock-skew allowance. A still
valid captured packet may be accepted after restart with fresh history. Possession
of a pairing key permits metadata creation/decryption; protect Core/app backups.
Already issued snapshots remain valid until expiry; immediate receiver revocation
requires disabling/removing pairing in Codex too. Accepted actions cannot be retracted.

**Recognition is not authentication or confidentiality.** False matches and replayed
speech remain possible. Account binding prevents cross-account use of voice context;
it does not prove who spoke. Do not authorise locks, alarms, purchases or confidential
data access from a match. HA's exposed-entity/Assist API boundary remains decisive.
The [speaker automation extension](SPEAKER_AUTOMATIONS.md) requires explicit automation
configuration; saved preferences alone cannot create a trusted speaker condition.

## Minimal request diagnostics

INFO sender/receiver/prompt records share a short hash of the encrypted header.
It correlates one request without logging its key, token, transcript, name/profile
ID, instructions or base prompt. Timing/outcomes still require protected retention.
Tags are not identity, authentication or a shared last-speaker API.

`receive` reports recognised/neutral/rejected and `instructions_present`;
`prompt_prepared` reports `instructions_applied`. These flags describe preferences,
not whether a name was supplied. Composition does not prove provider delivery or
model compliance. Plain requests inherit no previous diagnostic tag.

For separately approved diagnostics, allow targeted INFO for
`custom_components.codex_assist.conversation` and
`custom_components.codex_assist.voice_match`, then use a fresh utterance. See the
[app diagnostic guide](https://github.com/DaFern/wyoming-voice-match-ha/blob/main/docs/PERSONALIZATION.md#request-diagnostics).
No universal HA/debug/provider log redaction is promised.

## Current acceptance and rollback

Ordinary direct-connected assistant operation is confirmed on the test installation.
That is not multi-person discrimination, simultaneous-device, accuracy or all-client
acceptance. See [testing](TESTING.md) and [beta gates](BETA_ACCEPTANCE.md).

To roll back, first select ordinary Whisper/original STT in affected assistants,
then disable Voice Match in Codex and the app endpoint. No voiceprint deletion or
re-enrolment is required. Code rollback needs its own reviewed backup/restart plan.
