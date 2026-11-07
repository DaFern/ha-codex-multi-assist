# Voice Match: one everyday STT choice

On HA **2026.10+**, an enabled, configured Codex entry provides **Voice Match** STT
using a private direct connection to the app's paired endpoint. The existing unique
ID, entity ID and pipeline bindings are preserved. The filename remains stable for
links. [Setup and privacy](VOICE_MATCH.md).

## Setup and lifecycle

Open **Configure → Voice Match** on the Codex entry, enter the internal app hostname,
**10352** and personalisation key, enable and save. The learning key is separate.
Personal instructions are optional. Metadata-only setup requires the peer to advertise
`voice-match-personal`; it does not prove pairing. Each received packet is verified.

Use this STT with a Codex conversation agent from the same entry and usual TTS.
Keep ordinary Whisper as fallback. Saving reloads the entry and stops its active
Voice Match requests; it does not create/select/edit a pipeline or default assistant.
The setup toggle initially defaults on, but activation needs valid saved settings.
Saved opt-outs stay off.

Before disabling, switch affected assistants to their fallback STT. Disabling removes
the active entity and pairing but retains the backend address and all saved voices.
Re-enabling uses the stable unique ID. Integration Python installation needs an
approved Core restart; changing configured options uses entry reload.

## Connections and compatibility

New setups require no extra `voice-match` or `voice-match-personal` Wyoming STT
entities. Ports **10350** and **10352** remain available; ordinary Whisper is still
required for learning controls. Existing source-based configurations keep working
until explicitly reconfigured. Merely opening setup does not migrate options.

After testing a direct connection, inspect all assistants/dependencies/external
clients before disabling or deleting any unused Wyoming connection through HA's
supported UI. There is no old-source review option or automatic cleanup. Do not
delete the app or ordinary Whisper. Unrelated providers remain visible in HA's picker.

## Clean text and private handoff

Stock Wyoming STT emits encrypted context as transcript text before Codex runs;
stripping it in the agent cannot clean an already emitted chat bubble. The direct
adapter instead verifies a successful nonempty packet and returns only spoken words
as a `str` subclass. Repr, JSON and frontend events contain plain text; the object
has no packet/key/profile attributes. No Core/frontend patch or shared last-speaker
sensor is used.

An entry-runtime registry binds the encrypted packet to the exact text object and
owning asyncio pipeline task, not text equality. The agent consumes it once, rechecks
key/expiry/text binding and applies entry-wide replay protection, conversation scope
and optional speaker automation dispatch. Identical concurrent words cannot collide.
The authenticated HA caller is never replaced by the speaker.

Capacity is 256 pending objects and 256 active tasks per entry. Key changes fail
closed. Weak references, task callbacks and expiry remove abandoned records even
if traces retain the clean text. Cancelling tasks cannot consume a new action turn.
Unload/options reload invalidates the adapter generation, clears pending packets and
cancels owned recording/handoff/model tasks—not unrelated plain Codex tasks. Nonce
protection survives reload.

The private backend loads Core's version-specific Wyoming dependency without creating
a Wyoming config entry or global Codex dependency pin. It validates metadata on the
audio connection, accepts only mono 16 kHz/16-bit PCM, streams upload/receive concurrently
and closes tasks/iterators on completion/cancellation. Bounds are 60 seconds of audio,
105 seconds per request and five seconds for metadata. No mutation/audio retry or
raw-header fallback occurs. Backend failure affects this STT availability, not other
Codex entities; metadata-only availability probes run every 30 seconds.

## Limits

- Object/task identity is **not a documented upstream HA metadata channel**. A string
  copy, JSON boundary or changed pipeline task loses context; no words/time/device
  lookup recovers it. Version-pinned native tests are mandatory.
- Setup cannot enforce the selected conversation agent at the STT stage. Use only
  the paired entry's agent; other entries reject the carrier and unrelated agents
  see only words, not trusted identity.
- Native sentence triggers can intercept before Codex even with local-first handling
  disabled. They do not inherit the private speaker condition. Avoid conflicts with
  the dedicated Voice Match trigger.
- No global log/trace secrecy, acoustic accuracy, provider compliance or confidential
  identity is guaranteed. Recognition never authorises sensitive actions.
- Installing code does not clean existing stock-Wyoming pipelines automatically.

## Verification

Fast tests cover one-shot/task/object/key/entry binding, replay, forgery, copying,
expiry, capacity and cancellation. Native HA STT-to-intent pipelines and real loopback
Wyoming peers cover clean event/JSON text, names with empty instructions, simultaneous
identical utterances, endpointing, service failure, source changes, entry unload and
native sentence interception. Audio/model/inference boundaries are synthetic;
pipelines do not establish physical TTS or microphone behaviour.

Ordinary direct-connected assistant use is confirmed on the test installation.
Multiple real speakers/devices, uncertain matches, phrase conflicts, key rotation,
failure/recovery and rollback still need measured acceptance. See [testing](TESTING.md).
