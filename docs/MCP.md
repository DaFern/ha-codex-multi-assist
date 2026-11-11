# MCP connections — read-only development preview

This is the first, deliberately restricted milestone of
[issue #8](https://github.com/DaFern/ha-codex-multi-assist/issues/8), not completion
of its voice-account binding, per-user permissions or approved-write requirements.
It requires **Home Assistant 2026.10+**. Existing Codex functionality retains its
2026.6 minimum. No installed server is automatically connected or authorized.

## Set up

1. Install/configure your MCP server independently. For the community HA-MCP
   integration, obtain the connect URL from its **Configure** screen. Do not paste
   secret connect URLs or bearer tokens into chat, source control or GitHub issues.
2. On the **Codex assistants** entry, choose **Configure → MCP servers → Add server**.
3. Enter a stable ID, such as `ha_mcp`, and the server's Streamable HTTP URL.
   This initial transport accepts **literal IP addresses only**, not DNS names.
   Use a local-network connect URL supplied by the server. Replacing the hostname
   of an HTTPS URL may break certificate validation; never disable TLS verification.
4. Connections default to disabled. To probe a local-network endpoint, explicitly
   enable both the connection and local-network access. For HA-MCP's local-only URL
   on `127.0.0.1:9584`, enable **Allow loopback endpoint** instead; this separately
   approves a service on the HA machine. Do not substitute another address unless
   HA-MCP is configured to listen there. HTTP exposes credentials and data to the
   network, so only use it on a trusted network. Public IP endpoints require HTTPS.
   Loopback is rejected unless its separate checkbox is enabled; link-local/cloud
   metadata, multicast and reserved destinations, embedded URL logins, redirects
   and environment proxies remain rejected.
5. If the endpoint needs a bearer token, enter one here. A secret-path connect URL
   may already authenticate without a separate token. OAuth login, legacy SSE-only
   endpoints, stdio and subprocess servers are not supported in this milestone.
6. Enable and submit to initialize MCP and discover tools. The next screen confirms
   connection and lists tools declaring `readOnlyHint: true`, excluding explicitly
   destructive tools. **Nothing is approved by default.** Read the server's tool
   documentation, select only appropriate read-only tools, and confirm your review.
   An empty selection grants no tools. Missing annotations mean unavailable, not
   permission to infer safety from a tool name. Do not relabel a write tool as read-only.
7. Saving uses HA's options API and existing integration reload behavior. After an
   independently approved code installation, a full Core restart is required first.
   Test from an authenticated HA administrator's Assist chat, using an innocuous read.

To disable a server, use **Edit or disable server**, select it, turn **Enable
connection** off and save. No probe runs when disabling, and its approvals clear.
Blank bearer-token input keeps the saved token; **Clear saved bearer token** removes
it. Editing a connection requires reviewing its tools again; previous selections
are not silently granted. Up to eight independent server IDs are supported.

## Security and identity

- All personalities share one entry-level policy. Selection of an assistant never
  changes permissions. Native device control remains in HA's normal Assist path;
  this adds no raw Home Assistant service bridge and does not change native policy.
- Only an active, non-system HA administrator identified by HA's request `Context`
  can discover approved tools for a turn or execute them. Unknown, deleted, inactive,
  non-admin and system accounts receive no MCP tools. User IDs in prompts or tool
  arguments are not identities. This is **administrator-only**, not arbitrary
  per-user HA permission mapping. Non-admin MCP tools remain denied.
- Recognized Voice Match packet v2 includes the administrator-assigned profile owner
  inside Fernet encryption. A voice turn can receive MCP tools only when that owner
  equals the active authenticated HA caller; the ordinary administrator check still
  applies, so MCP remains admin-only and read-only. HA's caller context is never
  changed or impersonated. Legacy v1, neutral/unassigned, inactive/system, missing
  and mismatched accounts receive no MCP tools. A satellite without a real HA user
  context cannot inherit a prior user's identity. This binding is not strong biometric
  authentication and does not grant permission to non-admins.
- Every native tool invocation checks the current account and saved server policy,
  discovers the remote definition again, validates arguments using HA's native schema,
  and compares its approval fingerprint before dispatch. Revocation is checked again
  before returning read data. Schema, annotation, name or description changes deny
  execution until reapproved. Disabled/removed connections and stale tool objects
  cannot reuse their previous authority. Cancellation is not swallowed.
- Annotations are untrusted hints, **not proof that a remote implementation is
  read-only**. Explicit admin review and trust in the endpoint are essential. There
  is no sandbox that prevents an approved remote tool from lying or changing its
  implementation without changing its definition. No known write tools, sensitive
  action approval workflow, or destructive operations are supported here.
- HA-MCP's own account may be an administrator. Approved read tools can therefore
  read information beyond Assist-exposed entities. That expanded access is separate,
  explicit, administrator-only permission, not inheritance of the caller's narrower
  entity permissions. Do not approve administrative reads you do not want shared
  with the Codex backend or authorized administrators.
- Request-local discovery cannot leak tools between simultaneous requests. Once MCP
  is configured, native conversation IDs are bound to the account and current admin
  status within this integration. Switching users, changing admin status, unknown
  ownership or eviction starts a fresh native conversation rather than replaying
  privileged history. This remains enforced after disabling MCP. Ownership is bounded
  to 512 in-memory conversations; HA restart clears both ownership and native history.
  Existing Voice Match speaker boundaries remain in force as well.

## Transport, results and diagnostics

The client negotiates protocol `2025-03-26`, initializes a fresh session for each
discovery/call, supports JSON and bounded POST SSE responses, follows pagination
(maximum eight pages/128 tools), and attempts session deletion afterwards. Tool-list
pages are bounded to 1 MiB each; actual tool-call responses remain bounded to 256 KiB.
Sessions are not pooled. It does not retry calls, redirect credentials, poll a
background event stream or fall back to another transport. A subsequent turn
reconnects afresh. Each session has a 20-second operation bound.

Namespaces use the server ID and remote name to derive a provider-safe stable
`codex_assist__mcp_…` name. Native HA owns dispatch and result replay. Remote
`isError`, structured content, malformed responses, failures and timeouts do not
become success claims. Remote output is untrusted data, not permission or instructions;
prompt guidance does not guarantee model immunity to injection. There is no AI Task
MCP support. Native devices, hosted search and speaker automation dispatch are unchanged.

The setup screen provides a read-only connectivity probe. Integration diagnostics
include fixed per-server health outcomes from conversation discovery/calls and redact
nested URLs and bearer tokens. Health is last observed, not continuous monitoring.
Invocation audit logs contain the HA context identity source/user, server ID,
namespaced tool, definition-bound approval and fixed outcome; never arguments,
remote content, URLs, tokens or exception messages. Stored secret URLs and tokens
remain sensitive in HA's config entries/backups. Remote read data and approved tool
descriptions/schemas are sent to Codex and can remain in native conversation history;
ordinary HA tool traces may also contain results. Review traces before sharing.

## Verification boundary

Synthetic tests cover destination rejection, initialization, pagination, sessions,
JSON/SSE parsing, bounds and cancellation; native HA tests cover options saving,
default deny, account changes, stale approvals, argument validation, concurrent
request isolation and two-assistant model/tool/result delivery. They do **not**
prove connectivity to a particular installed HA-MCP version, remote read-only
behavior, real-model compliance or safe public deployment. Live HA-MCP discovery
and an approved read remain separate acceptance steps. No runtime configuration,
deployment or Core restart is performed by these tests.
