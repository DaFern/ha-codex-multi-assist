# Optional per-person response preferences

Experimental connector for **Wyoming Voice Match 0.3.0** and **Codex Multi-Assist
0.7.0**. It is off by default, with no changes to saved agent personalities or
AI Task settings. Full setup/transport/rollback documentation is maintained in
[the add-on repository](https://github.com/DaFern/wyoming-voice-match-ha/blob/main/docs/PERSONALIZATION.md).
That link becomes available once the paired repository changes are pushed.

After both reviewed updates pass CI and are deployed:

1. In Voice Match, assign voice ownership and set **Personal instructions**.
2. An administrator creates a pairing key in that add-on. Copy it directly into
   **Configure → Voice Match personal preferences** here. Never paste it in chat,
   screenshots, logs or issues. The password field is not prefilled; blank keeps
   an existing key. Disable the option to remove it. Diagnostics redact the key.
3. Enable the add-on's personalised endpoint and add its separate Wyoming STT
   connection on **10352**, not the normal **10350**. Use a separate test pipeline
   with a paired Codex agent; disable local-first intent handling if offered.
4. Test with multiple enrolled people and simultaneous devices. Until then, keep
   ordinary STT/Whisper available as a fallback. Do not enable the endpoint with
   unrelated conversation agents or an intent-only pipeline.

Personal instructions are added **after** HA renders the agent's base prompt.
They are literal text, not HA/Jinja templates. They are shared with the selected
provider for a matched request. Prefer short style/default instructions; never
store secrets or sensitive facts. The current agent/model/reasoning/tools remain
unchanged, and the original HA caller context is retained—not replaced by the
account linked to the recognised voice.

The add-on uses an encrypted, authenticated, utterance-bound request header because
standard Wyoming STT discards extra speaker fields. The connector verifies it,
checks expiry/replay and strips it before preparing model input. Invalid, expired,
replayed or unpaired headers fail closed, not as a raw prompt or a trusted name.
The add-on's conservative match/gap checks choose a preference profile; accepted
but uncertain speech uses neutral instructions with fresh context. Existing
acoustic rejection is unchanged.

## Conversation history

**Visible transcript limitation:** the current stock Wyoming path displays the
encrypted header in Assist's user-message bubble. Codex removes it after HA's STT
event has already been sent to the frontend. See the unregistered, experimental
[clean STT adapter prototype](CLEAN_SPEAKER_STT_PROTOTYPE.md); it is not a setting
that can be enabled on the existing endpoint yet.

When paired, context is bounded to the current speaker/revision and agent within
the provided HA conversation. Speaker/agent changes, changed preferences/ownership,
uncertainty, idle expiry or restart reset the scope. An earlier speaker returning
does not recover their old branch. No history is fetched by recognised identity.
Unpaired ordinary requests retain the previous conversation path; enabling pairing
starts a new scope, including for plain requests under that entry.
After pairing has been enabled, disabling it keeps scope isolation for that
entry's running lifetime so old mixed HA log history cannot reappear. A Core
restart clears both volatile speaker scopes and HA's in-memory conversation logs.

Only scoped turns and their tool/native output are replayed. A request cannot
rewrite a different current turn or include a later concurrent user's turn.
Provider session/cache IDs are salted per active scope. Normal HA conversation
logs/retention are not erased or converted into separate authenticated user logs.
This may reduce prompt-cache hits and increase token usage/latency compared with
the ordinary entry/agent cache; live costs have not been measured.

**Recognition is not authentication or a privacy guarantee.** False accepts/replay
of actual voices remain possible. The pairing authenticates the source of metadata,
not the human. Do not retrieve confidential data or authorise sensitive actions
solely from voice identity. The model's preference instructions are guidance, not
a security policy. HA's existing Assist API/exposed-entity checks remain decisive.

The replay cache is volatile, bounded and entry-scoped. It survives ordinary entry
reloads but not a Core restart; a captured still-valid header could be accepted
after restart with fresh history. Payloads expire after 120 seconds (with Fernet
clock-skew allowance). No guarantee of redaction across all HA/debug/provider logs
is made, and possession of a pairing key permits metadata creation/decryption.

## Minimal request diagnostics (development)

The add-on's sender decision, this receiver and prompt composition now have
correlatable INFO diagnostics in the development code. See
[the sender's diagnostic guide](https://github.com/DaFern/wyoming-voice-match-ha/blob/main/docs/PERSONALIZATION.md#request-diagnostics-development-not-deployed)
after both reviewed changes are pushed. A short hash of ciphertext correlates a
single request without logging its key, token, transcript, name/profile ID,
personal instructions or base prompt. Normal log timing/outcome privacy still
applies; tags are not authentication or a last-speaker API.

`receive` reports recognised/neutral/rejected and `instructions_present`.
`prompt_prepared` reports `instructions_applied` for each composition attempt;
it does not prove provider delivery or model compliance. The unregistered clean
STT prototype uses the same tag as its original encrypted packet. Plain/unpaired
requests do not inherit an older tag or produce a recognised-person diagnostic.

Allow INFO only for `custom_components.codex_assist.conversation` and
`custom_components.codex_assist.voice_match` when diagnosing, with separate
approval for runtime logging changes. The implementation changes no live logging
levels. New deployment and a fresh utterance are required; prior requests have no
retained diagnostic snapshots. No pairing rotation or protocol change is needed.

## Deployment and rollback

The development-only [speaker automation extension](SPEAKER_AUTOMATIONS.md) adds
a Voice Match sentence trigger and a reusable Recognised speaker is condition.
It needs separate review/deployment; personal instructions alone cannot supply
an automation's speaker identity.

This source change is not a live deployment. Updating integration Python requires
an explicitly approved full Core restart; update/back up the add-on separately.
Keep current personalities and AI Task defaults. Disable this connector and switch
back to ordinary STT to roll back the feature without removing voiceprints.

The corresponding user-guide/wiki section should be published only after the
reviewed changes are committed/pushed; that external wiki publication is pending.
