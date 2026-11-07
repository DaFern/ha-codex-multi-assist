# Combined integration

One custom HACS integration, `codex_assist`, provides independent **Codex assistants**
and **Voice Match learning** entries. The Voice Match app is installed separately.
Source version is **0.7.0**, app **0.4.7**; identify exact revisions as well.
**No combined public beta is published.** [Installation](INSTALLATION.md).

## Independent modules

The module menu is shown before network requests. Codex alone requests OAuth,
discovers models and provides conversation agents plus one shared AI Task entity.
It supports HA **2026.6+** and needs no Voice Match app or Whisper.

Learning requires **HA 2026.10+**, the app, ordinary Wyoming Whisper, TTS and a normal
Companion login, but no Codex account. It verifies an encrypted bridge handshake
and offers phone learning off by default. Only an enabled learning entry forwards
its STT and non-LLM conversation entities. It never forwards AI Task or schedules
Codex model refresh. Entry unload/reconfigure/reauth stays module-scoped.

Shutdown pauses unfinished learning, not sample deletion or replacement. Unverified
shutdown/restoration refuses unload rather than forgetting state; it does not unload
Codex. Codex options/reauth do not replace the learning runtime. Diagnostics redact
credentials, prompts and private bridge fields. One Codex sign-in is supported.

## Clean development setup (not a live cutover instruction)

1. Install the integration and separate app using the [installation guide](INSTALLATION.md).
   Do not run standalone `voice_match_enrollment` and combined learning together.
2. Add **Codex Assist → Voice Match learning**. Select a metadata-suggested address
   or enter the app's internal HTTP origin on **8099** manually. Enter the separate
   **learning key** from **Administrator settings → Voice Learning connection**.
   Suggestions confer no trust; an encrypted handshake verifies pairing.
3. Explicitly enable phone learning with ordinary Wyoming Whisper, not a filtering,
   personalised or recursive learning endpoint. Provider/language checks cannot
   prove which backend a Wyoming source uses. Review and submit to save.
4. Manually create **Voice Learning** with both learning entities and usual TTS.
   No pipeline, global default or ordinary assistant is changed automatically.
5. Use an own-account uniquely assigned profile and normal Companion login. The
   management Learn/Resume button requests the dedicated native assistant; manual
   selection is the fallback. Hear the notice and separately say **Start learning**.
6. Only saved samples advance the guided phrase. **Pause learning** retains samples;
   a verified paused scope previews the count and needs separate **Continue learning**.
   New/expired/interrupted scopes require fresh notice and **Start learning**.
   **Cancel voice learning** discards only the bound unfinished session, not the
   installed voiceprint. Never blindly retry uncertain mutations.

Pairing, entity enablement and launch are not recording consent. Initial, consent
and control turns are never samples. Ordinary Assist traffic never trains.

## Completion and return to normal use

The final prompted sample has a bounded read-only completion wait: up to 15 extra
seconds, at most 30 status reads at 0.5-second spacing, within the same native turn.
Only a validated installation/cleanup receipt is success. Rejected samples repeat;
errors retain attention warnings. Continued processing explicitly ends the automatic
check and directs the user to management or a status request. No background polling
or unsolicited replacement of an already-sent reply occurs.

The wait rechecks authenticated scope before/after reads and stops on revocation,
disconnect, expiry, unload or removed flow. It never resubmits audio or retries a
failed mutation. Confirmed pause/cancellation/completion appends a spoken reminder
to select the regular assistant manually. Unverified outcomes do not claim success.

## Native launcher

The authenticated `/voice-match-learning` panel resolves registry IDs, current
login and own profile, and requires exactly one enabled matching learning assistant.
Read-only discovery uses `codex_assist/voice_learning/launch_info`; frontend code
is served at `/codex_assist/voice-learning-launch-v2.js`.

It requests native `assist/show` once, then navigates the underlying HA page to
Voice Match management when one safe metadata-verified app route matches the
configured origin. This is not native acknowledgement, Assist dismissal, consent
or restoration of the previous assistant. Missing/ambiguous/unsafe metadata uses
the manual fallback. **Back to Voice Match** or **Back to Home Assistant** remains
available after uncertain dispatch; failure does not retry the consumed launch.
The panel never overwrites a conflicting standalone launcher.

## Check setup and Repairs

Learning options separate **Check setup**, phone settings, pairing repair and optional
personalisation guidance. Checks report bridge, source, learning entities, dedicated
assistant and launcher independently. They do not verify own-profile readiness,
consent, actual microphone handoff or acoustic quality.

An explicit check makes a bounded encrypted `hello`, not a learning mutation.
Checks run on observed transitions/request, not continuous network polling. Stale
configuration results remain **not checked**. Entry-scoped Repairs offer confirmed
Reconfigure, source settings or instructions/recheck. Unknown results cannot count
as fixed; unresolved issues/dismissal state survive reload. Removal cleans only that
entry's issue IDs. Failed unload is not successful disablement.

Checks/repairs do not install apps, adopt/rotate keys, create assistants, record,
delete, reassign profiles or change defaults. A complete end-to-end administrator
onboarding wizard is still [app issue #4](https://github.com/DaFern/wyoming-voice-match-ha/issues/4).

## Everyday Voice Match

On the Codex entry choose **Configure → Voice Match** and enter the app hostname,
**10352** and its distinct personalisation key. Use **Voice Match** STT with a Codex
agent from that entry. No second Wyoming STT integration is required. Recognised
names work without personal instructions. Learning remains separate and works
without Codex. [Privacy and scoping](VOICE_MATCH.md).

## Limits and acceptance

No secure automatic key adoption, automatic assistant creation, production satellite
learning adapter, accountless Echo admission or exact previous-assistant restoration
is supplied. Recognition is not authentication or authority for sensitive actions.

Tests cover native HA lifecycle/authentication/pipelines, exact-turn handoff,
loopback encrypted bridge and Wyoming protocol with synthetic audio/inference.
Ordinary direct-connected assistant use and the app's admin layout are confirmed
on the test installation. Short notice/timely pause-resume have narrow phone
acceptance. The current combined full 30-sample replacement/cleanup, privacy details,
resume-prompt cancellation, fresh installs, wider device/recognition tests and
rollback remain open. [Testing](TESTING.md) and [candidate beta gates](BETA_ACCEPTANCE.md).
