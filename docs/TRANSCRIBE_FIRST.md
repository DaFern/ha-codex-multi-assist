# Transcribe first, authorise afterwards

This development change pairs the Voice Match app's default-off
`transcribe_unmatched` option (0.4.9) with protected satellite replies.
It does not enable or extend any guest role or device permission.

## Speech is not authority

On the paired personalised connection only, enabling the option lets unmatched
speech reach ordinary Whisper. The result is an encrypted neutral packet without
a recognised speaker/account. It does not inherit the previous person's access.
The existing fresh guest/user projection and per-action native/RBAC checks still
decide whether a device action may run. A missing guest role still denies actions.
The standalone Wyoming filtering endpoint remains unchanged.

Matched audio keeps the existing speaker extraction and independent identity
assessment. Speech acceptance and identity thresholds are different settings:
loosening the former does not lower the latter or authenticate an uncertain
speaker. Background TV/other voices can now produce guest requests. This tradeoff
requires administrator opt-in; it is not a background recording/training feature.

## Finite public replies

After a private one-use STT handoff is consumed and verified on the current
encrypted satellite admission, exact closing/time phrases may receive fixed
replies before device-role/tool discovery:

- Standalone thanks/thank you: “You're welcome.” then standby.
- Existing stop-listening/goodbye phrases: fixed acknowledgement then standby.
- Exact current-time questions: the current HA-configured local time, including
  DST, directly from the clock. No model or external time service is involved.

These replies receive no tools, personal instructions, previous speaker context,
history or device data. They do not append durable dialogue or erase existing
history. Time replies retain the ordinary follow-up listening window; closings
do not reopen it. Compound requests such as “thanks, unlock the door” and queries
about alarm times/calendars do not match the public path and retain normal checks.
Changed transport/key/expired admissions, raw/forged transcripts and replayed
packets still fail closed.

## Denials

The protected model is instructed to explain when the requested action/device
is outside the current speaker's permitted context. It may refer to the target
description in the user's own request, but must not confirm hidden devices or
reveal their state/owners. Explicit denied tool results receive a fixed
“You're not authorised to control that device.” reply.
Unavailability, transport failure, ambiguity and uncertain execution are not
misrepresented as permission denials.

## Deployment and acceptance

The app option needs an updated/rebuilt 0.4.9 image and an app restart.
Integration Python changes need their separate deployment and Core restart.
No automatic offer routing, briefing logic, permission assignment or learned
voiceprint is changed by this work.

Automated tests use simulated recognition/model/network responses, not physical
microphone or multi-speaker acceptance. The local native environment is HA 2026.10,
not the installed 2026.11 build. Verify time, standalone thanks, compound
thanks-plus-command, guest permitted/denied requests, speaker switches and
background speech physically before considering acceptance complete.
