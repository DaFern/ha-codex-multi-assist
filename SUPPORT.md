# Support

## Questions and setup help

Start with this fork's [installation and support matrix](docs/INSTALLATION.md),
[combined learning guide](docs/COMBINED_INTEGRATION.md) and
[acceptance/rollback checklist](docs/BETA_ACCEPTANCE.md). Upstream wiki pages
are background for shared Codex features, not this fork's install instructions.

There is **no published combined beta**. Development builds are identified by
commit SHA as well as source version `0.7.0`; identical version strings do not
prove identical code. Codex retains HA **2026.6+** support, while learning requires
**2026.10+**. The planned combined beta acceptance baseline is HA 2026.10+ on
amd64 HAOS; that does not raise the Codex-only floor or certify untested releases.
HA 2026.11/Marketplace installation and other hardware require separate evidence.
No support claim extends to satellite capture, accountless Echo enrolment or
automatic previous-assistant restoration. Report fork-specific bugs here, not upstream.

For a quick first check:

1. restart Home Assistant after installing or updating;
2. confirm Codex Assist appears under **Settings → Devices & services**;
3. confirm the selected Assist pipeline uses Codex Assist;
4. complete reauthentication if Home Assistant offers it;
5. test with one harmless exposed light or a read-only question.

## Bugs and feature requests

Use this fork's [issues](https://github.com/DaFern/ha-codex-multi-assist/issues).
Coordinate cross-component work in [Voice Match issue #5](https://github.com/DaFern/wyoming-voice-match-ha/issues/5).
Include the Home Assistant version, integration commit/version, add-on version if
used, selected module and minimal reproduction steps with only redacted logs.

Do not post tokens, device codes, cookies, Home Assistant secrets, private URLs, config entries, or unredacted screenshots.

## Security issues

Do not open a public issue for a vulnerability or credential exposure. Follow [SECURITY.md](SECURITY.md) for private reporting and rotation guidance.

Codex Assist is unofficial experimental software. Problems with ChatGPT accounts, subscription access, or the official Codex service should be handled through OpenAI support; Home Assistant platform issues unrelated to this integration belong in Home Assistant's support channels.
