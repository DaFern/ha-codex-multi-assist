# Codex Multi Assist for Home Assistant

**Development fork — not a published combined beta.** This repository is
`DaFern/ha-codex-multi-assist`, not the upstream HACS default-catalog integration.
It contains one `codex_assist` integration with independent Codex and optional
Voice Match learning entries. See the [installation and beta policy](docs/INSTALLATION.md)
and [acceptance/rollback checklist](docs/BETA_ACCEPTANCE.md) before installing.

<p align="center">
  <img src="assets/codex-assist-icon.png" alt="Codex Assist icon" width="128" height="128">
</p>

<p align="center">
  <a href="https://github.com/DaFern/ha-codex-multi-assist/actions"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/DaFern/ha-codex-multi-assist/ci.yml?branch=main&style=for-the-badge&label=CI"></a>
  <a href="docs/INSTALLATION.md"><img alt="HACS custom repository; development only" src="https://img.shields.io/badge/HACS-Custom%20repository-41BDF5?style=for-the-badge"></a>
</p>

Use OpenAI Codex / ChatGPT as a Home Assistant Assist conversation agent and AI Task provider.

Codex Assist signs in with Codex-style ChatGPT device-code auth. It keeps device control inside Home Assistant's normal exposed-entity safety model and does not require an OpenAI API key.

> Experimental: this project is not affiliated with OpenAI or Home Assistant. Codex backend compatibility may change with upstream Codex updates.

## Quick start

**Optional MCP development preview:** on HA 2026.10+, configure multiple Streamable
HTTP servers under **Configure → MCP servers**. Connections and tools default to
denied. Only authenticated HA administrators can use explicitly reviewed read-only
tools; Voice Match grants no access. Literal-IP endpoints only in this first
milestone; no writes, OAuth, stdio or legacy SSE-only transport. Read the
[setup, permissions and limitations](docs/MCP.md) before enabling it.

For Codex you need Home Assistant `2026.6.0` or newer and a ChatGPT account or
plan with Codex access. Optional voice learning requires **HA 2026.10+**, the
separate [Voice Match add-on](https://github.com/DaFern/wyoming-voice-match-ha),
ordinary Wyoming Whisper and TTS, but **no ChatGPT account**.

[![Open fork in HACS (development only)](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=DaFern&repository=ha-codex-multi-assist&category=integration)
[![Add the Codex Assist integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=codex_assist)

### 1. Install

Use a disposable test installation until the combined beta passes its acceptance
gates. This fork needs a **custom repository**, not the upstream default entry.
Do not install upstream and this fork together: both own `codex_assist`.

1. Open **HACS → ⋮ → Custom repositories** (labels may differ in Marketplace).
2. Add `https://github.com/DaFern/ha-codex-multi-assist`, type **Integration**.
3. Open **Codex Multi Assist**, confirm the repository owner is **DaFern**, and
   review the selected revision before **Download**. With no releases, HACS uses
   the default branch; moving `main` is not a pinned beta.
4. Restart Home Assistant after approved installation. Search **Codex Assist**
   under Devices & services; that is the integration's display name.

The button above opens a repository, not an installer or recording-consent flow.
Existing upstream or standalone-companion installations need a separately reviewed
cutover, not these fresh-install steps. See [the full guide](docs/INSTALLATION.md).

### 2. Choose a module

For **learning only**, select **Voice Match learning**, not Codex assistants, and
follow [learning setup](docs/COMBINED_INTEGRATION.md#clean-development-setup-not-a-live-cutover-instruction).
Skip the Codex sign-in and agent-selection steps below. Personalisation is optional
and uses a separate key only if you later add Codex.

After requesting native Assist, the launcher returns the underlying
page to Voice Match management when a safe add-on route is available. This does
not confirm Assist opened or grant recording consent. The one-shot launch guard
stays enabled; a **Back to Voice Match** link remains if dispatch is uncertain.
See [launcher boundaries](docs/COMBINED_INTEGRATION.md) for fallback limitations.

Confirmed pauses, cancellation and validated learning completion now end with:
“If you're finished with voice learning, remember to switch back to your regular
assistant.” This reminder does not switch assistants automatically.

After the final phrase, the learning agent waits up to 15 additional
seconds for confirmed completion and announces success in the same turn. If it
is still processing, the reply explicitly says the automatic check has ended and
directs you to Voice Match management or a spoken status request.

For **Codex**, follow these sign-in steps:

Sign-in uses a device code, so you approve it in a browser. The browser can be on any device.

1. Go to **Settings → Devices & services → Add integration**, or use the button above. Search for **Codex Assist** and select it.
2. Select **Codex assistants**, then **Submit**. Home Assistant shows a web address and a short code.
3. Open that address in a browser, sign in to ChatGPT, and enter the code.
4. Return to Home Assistant and select **Submit**. If it says the code has not been approved yet, wait a few seconds and select **Submit** again.
5. Choose a chat model from the list, then select **Submit**.

If sign-in does not start or the code page reports an error, device-code login may be turned off for your account. OpenAI's [authentication guide](https://learn.chatgpt.com/docs/auth) says a personal account enables it in ChatGPT security settings, and a workspace admin controls it for a workspace. Home Assistant stores the sign-in itself. Do not paste tokens or copy them from Codex CLI or another tool.

Codex Assist supports one sign-in. To change accounts or sign in again, use **Reconfigure** on the existing entry.

**Optional Voice Match learning:** setup offers a
separate learning entry with verified bridge pairing and an explicit phone opt-in.
Learning requires HA **2026.10+**, the add-on and ordinary Wyoming Whisper—not a
Codex account. Codex still needs neither the add-on nor voice setup. The learning
entities and native launcher live inside this integration; no second custom
integration is needed. This is **not** a released combined beta. See
[setup, boundaries and the separate cutover gate](docs/COMBINED_INTEGRATION.md).

The learning setup flow can suggest an internal add-on address from
Home Assistant's cached Supervisor metadata, but still requires your learning key
and verified pairing. It ends with a separate review before saving. **Configure →
Check setup** reports technical readiness; **Repairs** explains observed problems
without resetting data or changing pipelines. Optional personalisation guidance
explicitly selects an existing Codex entry and never copies the learning key.
These checks do not replace clean-install or real-phone acceptance.

### 3. Choose Codex Assist in your pipeline

1. Go to **Settings → Voice assistants**.
2. Open an existing assistant, or select **Add assistant**.
3. Set **Conversation agent** to **Codex Assist**.

### 4. Try a safe first request

Expose one harmless entity to Assist before you ask anything. A single light or a read-only sensor is a good choice. Open **Settings → Voice assistants** and use the **Expose** tab. [Safe Entity Exposure](https://github.com/itsreverence/ha-codex-assist/wiki/Safe-Entity-Exposure) has the steps and the entities to keep unexposed.

Then ask Assist about it by its own name. For example, if you exposed a light named Desk lamp:

```text
Is the desk lamp on?
```

<p align="center">
  <img src="assets/codex-assist-light-control.png" alt="Example Assist chat in which Codex Assist reports that yard lights are on and turns them off" width="430">
</p>

If something fails, start with [Troubleshooting](https://github.com/itsreverence/ha-codex-assist/wiki/Troubleshooting).

## What it does

**Assist conversations.** Codex Assist registers as a normal Assist conversation agent and streams replies. It reads and controls only the entities you expose to Assist, through Home Assistant's own Assist LLM API.

Device commands recognised by native Assist are routed through existing authorised
intent tools before asking the model. Shared result handling covers all tool/device
types: replies acknowledge accepted, failed or partial requests without inventing
physical completion. A tools-disabled reply step uses the selected agent's saved
instructions to write the entire acknowledgement in its personality, without a
mandatory stock sentence or fixed prefix/suffix.
This supports user-created agents as well as starter personalities. If generation
fails or its result is invalid, the factual acknowledgement remains the fallback;
actions are never repeated just to improve wording. This adds a model call/latency.
Unrecognised wording still uses the model path, so this is not a
universal language or truth verifier. See [scope and limitations](docs/ACTION_CONTROL.md).

On HA 2026.8+, every Codex conversation profile can also use a read-only attribute
tool for approved details omitted by HA's live context, such as weather wind speed,
pressure and thermostat settings. It checks exposure and caller read permissions,
returns units/missing values honestly, and has no four-agent limit. It is not an
unrestricted attribute dump. See [supported attributes and safeguards](docs/ENTITY_ATTRIBUTES.md).

### Voice Match and optional response preferences

The experimental Voice Match connector can add a recognised person's response
preferences to the selected agent without changing its personality or HA
permissions. It requires explicit pairing and reviewed add-on/integration updates;
personal instructions are optional, not a separate STT mode.
See [setup, privacy boundaries and rollback](docs/VOICE_MATCH.md). It does not
authenticate speakers or retrieve private conversations by recognised identity.

Voice Match supplies the matched voice profile's display name to
the agent, even without saved personal instructions. This lets it acknowledge a
recognised speaker naturally, without treating recognition as a login.

The experimental [speaker automation extension](docs/SPEAKER_AUTOMATIONS.md)
adds a **Voice Match sentence** trigger and **Recognised speaker is** condition.
Reuse one voice profile across automations, without a shared last-speaker sensor.
It requires separate reviewed deployment and must not authorise sensitive actions.

The setup offers one everyday **Voice Match** STT choice
on HA 2026.10+: configure its internal backend address and personalisation key
under **Configure → Voice Match**, then select it with a Codex agent from that
entry. Chat transcripts stay clean, recognised names are retained, and personal
instructions are optional. New setups need no separate `voice-match` or
`voice-match-personal` Wyoming STT entities. **Voice Learning** remains separate.

Existing Clean voice messages entity IDs and pipeline bindings are preserved;
legacy source connections continue until explicitly reconfigured. Setup does not
remove existing engines or hide unrelated STT providers. Installing code does not
change existing pipelines. Ordinary direct-connected assistant use is confirmed on
the test installation; multi-speaker/device accuracy remains unverified.
See [setup, migration and limitations](docs/CLEAN_SPEAKER_STT_PROTOTYPE.md).

[Request diagnostics](docs/VOICE_MATCH.md#minimal-request-diagnostics)
can distinguish neutral matches, missing preferences and local prompt application
without logging names, keys, transcripts or instruction text. Targeted runtime
logging-level changes require separate approval.

### Multiple conversation assistants

One Codex Assist config entry can provide several independently configurable
conversation agents. In the integration's **Configure** options, choose
**Manage conversation assistants** to add, edit/rename, or remove assistants.
JARVIS, F.R.I.D.A.Y., and Ultron are created as starter personalities; you can
change their names, instructions, model, reasoning, response length, and optional
hosted web search, or create your own. All agents share the entry's Codex sign-in,
but have separate Codex sessions and only receive their own conversation turns.
The existing Codex Assist entity keeps its unique ID and serves as the primary
agent for existing pipelines. AI Task continues to use the shared AI Task defaults.
Edit the shared **AI Task system prompt** under **Shared AI Task defaults → Advanced AI Task settings**;
edit a conversation agent's prompt under **Manage conversation assistants**. Changing the
shared prompt does not change saved conversation-agent prompts.

Existing installations migrate automatically on reload: the existing agent keeps
its current settings and session identity, while the three starter personalities
are added. Review [the multi-agent migration and rollback guide](docs/MULTI_AGENT_MIGRATION.md)
before deploying a development build over an existing installation.

**AI Task.** It generates plain text or structured data, reads supported image attachments (up to four images, 10 MiB each, 20 MiB total), and generates images. See the [AI Task example](https://github.com/itsreverence/ha-codex-assist/wiki/Features-and-Options#run-a-data-task).

**Hosted web search.** Off by default. When on, the model can search for current information. The model is asked to keep raw URLs out of spoken replies, which is not guaranteed.

**Options.** The chat model comes from your account's own model list. See [Choosing a Model](https://github.com/itsreverence/ha-codex-assist/wiki/Choosing-a-Model) and [Features and Options](https://github.com/itsreverence/ha-codex-assist/wiki/Features-and-Options).

If a response ends before it completes, Codex Assist reports a failure. Part of the reply may already have been shown or spoken, so check a device's state before you repeat a request.

## Privacy and safety

- Codex Assist has no raw "call any Home Assistant service" bridge. Control goes through Home Assistant's Assist LLM API, so your list of Assist-exposed entities is the practical safety boundary.
- Each Assist request sends your message and the instructions Home Assistant builds for the model to the Codex service. Those instructions include an overview of your exposed entities. In Home Assistant 2026.10 the overview has names, areas, and aliases, and current states are sent only when the model asks for them. Other versions can differ. Expose only what you are comfortable sharing.
- Keep locks, alarms, garage doors, water shutoff valves, covers, and other sensitive devices unexposed unless you want Assist to control them.
- Hosted web search also sends the model's search queries to the Codex backend. AI Task prompts and supported attachments are sent when you run those tasks.
- Diagnostics redact access tokens, refresh tokens, and prompts. Review them before you share them.

The [security policy](SECURITY.md) has the full data and control boundaries.

## User guide

This fork's [installation guide](docs/INSTALLATION.md), [combined design](docs/COMBINED_INTEGRATION.md)
and [support policy](SUPPORT.md) are authoritative for fork-specific features.
The following [upstream wiki](https://github.com/itsreverence/ha-codex-assist/wiki)
is background for shared Codex features only; its installation/release guidance
does not install this fork or describe optional learning.

- [Installation](https://github.com/itsreverence/ha-codex-assist/wiki/Installation)
- [Safe Entity Exposure](https://github.com/itsreverence/ha-codex-assist/wiki/Safe-Entity-Exposure)
- [Features and Options](https://github.com/itsreverence/ha-codex-assist/wiki/Features-and-Options)
- [Choosing a Model](https://github.com/itsreverence/ha-codex-assist/wiki/Choosing-a-Model)
- [Troubleshooting](https://github.com/itsreverence/ha-codex-assist/wiki/Troubleshooting)
- [Compatibility and Limitations](https://github.com/itsreverence/ha-codex-assist/wiki/Compatibility-and-Limitations)

## Project docs

- [User support](SUPPORT.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Testing](docs/TESTING.md)
- [Release process](docs/RELEASING.md)
