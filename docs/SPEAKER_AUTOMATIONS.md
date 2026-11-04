# Speaker-aware automations (development, not deployed)

Use **Codex Assist: Voice Match sentence** as the trigger, then
**Codex Assist: Recognised speaker is** as a condition or in a `choose` branch.
Enter the existing profile ID shown in Voice Match's Manage voices. One person
has one profile ID across every automation; do not create per-automation voices.
This checks a recognised acoustic profile, not a logged-in Home Assistant user.

## Requirements

- Both reviewed components installed, with the existing pairing enabled.
- The personalised Wyoming STT endpoint on 10352 and a paired Codex agent.
- Local-first intent handling disabled so the request reaches that agent.
- This development change installed after review and an approved Core restart.

The condition is reusable, but not a global sensor. A native time, motion, event,
manual run or ordinary sentence trigger has no matching speaker and returns false.
An ordinary typed transcript cannot claim a voice, even by naming someone.

## Example

This illustrative automation returns a greeting only. It does not configure any
home-specific calendar, news source or device action.

```yaml
alias: "Personal greeting"
triggers:
  - trigger: codex_assist.voice_sentence
    options:
      sentence:
        - "good morning"
        - "good evening"
actions:
  - choose:
      - conditions:
          - condition: codex_assist.speaker_is
            options:
              voice: "alice"
        sequence:
          - set_conversation_response: "Good morning, Alice."
      - conditions:
          - condition: codex_assist.speaker_is
            options:
              voice: "bob"
        sequence:
          - set_conversation_response: "Good morning, Bob."
    default:
      - set_conversation_response: "Good morning. I could not select a personal briefing."
mode: parallel
max: 4
```

Sentences are literal: case, repeated whitespace and final sentence punctuation
are ignored. Wildcards, templates and Hassil sentence syntax are not interpreted.
All matching configured triggers run; avoid overlapping triggers if actions
should happen only once. A single automation with `choose` is usually simplest.
The first non-empty conversation response is returned. With no response, the
agent says there is no configured response rather than claiming actions succeeded.
Add the native **Set conversation response** action for speech through the current
Assist pipeline/Piper voice. Configured sentence replies bypass the model, so write
their wording explicitly; ordinary unmatched conversation keeps its personality.

## Request isolation and limits

The existing encrypted packet is verified for expiry, replay and utterance binding
before dispatch. No protocol/key change or Voice Match add-on update is needed.
The connector carries the decoded profile directly into each trigger callback.
It never reads the conversational scope or a shared last-speaker entity to decide
who triggered an automation. Unknown/uncertain packets can reach a general default
branch but cannot match a named profile. Invalid packets do not trigger anything.

An in-memory registry accepts only the exact metadata object attached to the
currently running callback. Copies of trigger traces, handwritten IDs and public
events cannot establish that association. The condition reads a separate captured
profile, not mutable fields in a template. Parallel device requests have distinct
records. Queued/delayed checks retain their original snapshot until that callback
finishes; they never switch to the latest voice. Completion, failure or cancellation
removes the record. At most 256 callback records can be active, with capacity
failure stopping the request instead of borrowing or evicting another identity.

HA owns automation execution. The original caller context is passed through; no
account is impersonated and no model-selected arbitrary service bridge is added.
Automations run their administrator-configured actions under HA's normal rules;
the speaker condition does not restrict what an automation is allowed to do.
Do not use a voice match alone to authorise locks, alarms, purchases, confidential
calendar access or other sensitive operations. Enforce genuine authentication and
confirmation separately. If a callback fails, the connector returns a fixed error
and does not fall through to the model or automatically retry completed actions.
HA's own configured automation error handling still applies.

The voice profile, clean sentence, device and satellite context may appear in HA
automation traces. Pairing keys and personal instructions are not added to trigger
data. This is not a confidentiality guarantee; do not publish unredacted traces.

## Rollback and verification

Disable the new trigger/automation or change the pipeline back to ordinary STT.
Removing this integration code requires restoring the prior build and another
approved Core restart. Existing Alexa routines, other automations, Piper, agent
profiles and AI Task are not modified by installing the code.

Fast tests exercise request isolation, unknown/plain/forged inputs, metadata copies,
capacity, unsubscribe, exceptions and cancellation. Real HA tests load the native
trigger/condition descriptions, run an automation with `choose` and conversation
responses, preserve caller context, reject packet replay, and check concurrent
conversation requests. Real voice accuracy, editor rendering, and physical-device
speech still need separate live acceptance after approved deployment.
