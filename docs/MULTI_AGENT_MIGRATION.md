# Multi-agent migration and rollback

## Compatibility behavior

The feature stays under the existing `codex_assist` domain and config entry. It
does not create another integration entry or request another Codex sign-in.
Before agent profiles have been saved, the integration derives its primary
profile from the existing config entry data/options, so the current prompt,
model, reasoning, response length, and web-search choices remain in effect.

The primary agent keeps the config entry's existing conversation entity unique
ID and Codex session ID. Existing Voice assistant pipelines therefore continue
to reference the same entity. On first setup/reload, JARVIS, F.R.I.D.A.Y., and
Ultron are added with distinct entity IDs, prompts, and Codex session IDs. Their
requests receive only turns attributed to that agent, plus the current user
turn. Authentication remains shared. AI Task entities and their shared options
are unchanged.

Agent profiles are stored in the config entry's options. Adding the first custom
profile persists all current profiles, including the primary's effective
settings. After profiles are persisted, edit the primary profile in the agent
manager to change its conversation-specific settings. The separate **Shared AI
Task defaults** page continues to control AI Task defaults.

## Before deploying

1. Run the project's fast suite, the supported Home Assistant contract suites,
   Ruff, and `git diff --check`.
2. Back up the current `custom_components/codex_assist` directory and note its
   exact contents/location. Do not remove the existing config entry.
3. Confirm the integration is still loaded from the same `custom_components`
   location and that no other copy of `codex_assist` will shadow it.
4. After replacement, perform a full Home Assistant restart; integration Python
   code is not activated by a config-entry reload alone.

## Verify after restart

- Confirm the existing Codex Assist conversation entity ID is unchanged and the
  existing Voice assistant pipeline still selects it.
- Confirm the three starter conversation entities are available and can each
  complete a harmless conversation.
- Confirm switching between agents does not expose another agent's prior turns.
- Confirm AI Task still works with the existing Codex sign-in and settings.
- Confirm entity control remains limited to entities exposed to Assist.

## Roll back

If any compatibility or runtime check fails, stop using the new agents and
restore the backed-up integration directory to the same
`custom_components/codex_assist` location, then perform a full Home Assistant
restart. Keep the existing config entry and its authentication data. The older
integration ignores the new `agents` option and continues to use its legacy
settings; restoring the directory does not require deleting the entry or
signing in again. Recheck the original conversation entity and pipeline after
Core returns.

The stored `agents` option can remain during rollback. If later returning to the
multi-agent build, it will resume those saved profiles. Removing them is
unnecessary and would discard user-configured assistant settings.
