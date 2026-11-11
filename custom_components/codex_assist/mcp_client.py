"""Bounded, opt-in Streamable HTTP MCP transport and default-deny policy.

The first milestone accepts literal IP addresses only: no DNS rebinding,
redirects, environment proxies, subprocesses or automatic transport fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
from contextlib import asynccontextmanager
from typing import Any

import httpx

CONF_MCP_SERVERS = "mcp_servers"
MAX_BYTES = 262144
MAX_DISCOVERY_BYTES = 1024 * 1024
MAX_TOOLS = 128
TIMEOUT = 20
PROTOCOL = "2025-03-26"


class MCPError(ValueError):
    """A fixed, credential-free failure safe for configuration UI."""


def validate_server(server: dict) -> None:
    """Allow only explicit destinations, never cloud metadata or host services."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,23}", server.get("id", "")):
        raise MCPError("invalid_server")
    try:
        url = httpx.URL(server["url"])
        address = ipaddress.ip_address(url.host)
    except (ValueError, KeyError, TypeError, httpx.InvalidURL):
        raise MCPError("invalid_endpoint") from None
    if (
        url.scheme not in {"https", "http"} or url.userinfo or url.fragment
        or (address.is_loopback and not server.get("allow_loopback"))
        or address.is_link_local or address.is_multicast
        or address.is_unspecified or (address.is_reserved and not address.is_loopback)
        or getattr(address, "ipv4_mapped", None) is not None
        or "%" in url.host
    ):
        raise MCPError("invalid_endpoint")
    if address.is_loopback:
        # Loopback is a separate explicit trust grant for a service on this HA host.
        if not server.get("allow_loopback"):
            raise MCPError("invalid_endpoint")
        return
    # Only ordinary RFC1918/ULA addresses may opt into local cleartext access.
    local = any(address in network for network in (
        ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"), ipaddress.ip_network("fc00::/7"),
    ) if address.version == network.version)
    if (not address.is_global and not local) or (local and not server.get("allow_local")):
        raise MCPError("invalid_endpoint")
    if url.scheme != "https" and not (local and server.get("allow_local")):
        raise MCPError("invalid_endpoint")


def fingerprint(tool: dict) -> str:
    return hashlib.sha256(json.dumps(tool, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def eligible(tool: dict) -> bool:
    """Annotations are necessary hints, not permission: admin approval is separate."""
    hints = tool.get("annotations", {})
    return (
        isinstance(hints, dict) and hints.get("readOnlyHint") is True
        and hints.get("destructiveHint") is not True
        and isinstance(tool.get("inputSchema"), dict)
        and tool["inputSchema"].get("type") == "object"
        and isinstance(tool.get("name"), str)
        and bool(re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", tool["name"]))
    )


def approved(server: dict, tool: dict) -> bool:
    return bool(server.get("enabled") and eligible(tool) and
                server.get("approved_tools", {}).get(tool["name"]) == fingerprint(tool))


def validate_result(result: dict) -> None:
    """Reject malformed tool output rather than reporting it as a successful read."""
    if (not isinstance(result.get("content"), list)
            or not isinstance(result.get("isError", False), bool)
            or ("structuredContent" in result
                and not isinstance(result["structuredContent"], dict))):
        raise MCPError("invalid_response")
    for block in result["content"]:
        if not isinstance(block, dict):
            raise MCPError("invalid_response")
        kind = block.get("type")
        valid = False
        if kind == "text":
            valid = isinstance(block.get("text"), str)
        elif kind in {"image", "audio"}:
            valid = isinstance(block.get("data"), str) and isinstance(block.get("mimeType"), str)
        elif kind == "resource":
            resource = block.get("resource")
            valid = (isinstance(resource, dict) and isinstance(resource.get("uri"), str)
                     and (isinstance(resource.get("text"), str)
                          or isinstance(resource.get("blob"), str)))
        elif kind == "resource_link":
            valid = isinstance(block.get("uri"), str) and isinstance(block.get("name"), str)
        if not valid:
            raise MCPError("invalid_response")


class MCPConnection:
    """One bounded request/session, no retries that could repeat an operation."""

    def __init__(self, server: dict, client: httpx.AsyncClient):
        self.server = server
        self.client = client
        self.headers = {"Accept": "application/json, text/event-stream",
                        "Accept-Encoding": "identity"}
        if token := server.get("bearer_token"):
            self.headers["Authorization"] = f"Bearer {token}"
        self.sequence = 0

    async def rpc(self, method: str, params=None, *, notification=False):
        self.sequence += 1
        request: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notification:
            request["id"] = self.sequence
        if params is not None:
            request["params"] = params
        async with self.client.stream(
            "POST", self.server["url"], headers=self.headers, json=request,
        ) as response:
            if not 200 <= response.status_code < 300:
                raise MCPError("connection_failed")
            # Avoid decompression bombs before the streaming byte bound applies.
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise MCPError("invalid_response")
            if method == "initialize" and (session := response.headers.get("mcp-session-id")):
                if len(session) > 512 or any(ord(c) < 32 for c in session):
                    raise MCPError("invalid_response")
                self.headers["Mcp-Session-Id"] = session
            if notification:
                return None
            content = bytearray()
            response_limit = MAX_DISCOVERY_BYTES if method == "tools/list" else MAX_BYTES
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > response_limit:
                    raise MCPError("response_too_large")
                if response.headers.get("content-type", "").startswith("text/event-stream"):
                    # A server may keep SSE open after its response. Stop at the
                    # matching complete event, without opening a background GET.
                    normalized = bytes(content).replace(b"\r\n", b"\n")
                    for event in normalized.split(b"\n\n")[:-1]:
                        data = b"\n".join(line[5:].lstrip(b" ") for line in event.split(b"\n")
                                          if line.startswith(b"data:"))
                        if data:
                            message = json.loads(data)
                            if isinstance(message, dict) and message.get("id") == request["id"]:
                                return self._result(message, request["id"])
            if response.headers.get("content-type", "").startswith("application/json"):
                return self._result(json.loads(content), request["id"])
            raise MCPError("invalid_response")

    @staticmethod
    def _result(message, request_id):
        if (not isinstance(message, dict) or message.get("jsonrpc") != "2.0"
                or message.get("id") != request_id or "error" in message
                or not isinstance(message.get("result"), dict)):
            raise MCPError("invalid_response")
        return message["result"]

    async def tools(self) -> list[dict]:
        tools = []
        cursor = None
        for _ in range(8):
            page = await self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            if not isinstance(page.get("tools"), list):
                raise MCPError("invalid_response")
            tools.extend(page["tools"])
            if len(tools) > MAX_TOOLS or any(not isinstance(t, dict) for t in tools):
                raise MCPError("invalid_response")
            cursor = page.get("nextCursor")
            if not cursor:
                names = [t.get("name") for t in tools]
                if any(not isinstance(n, str) for n in names) or len(set(names)) != len(names):
                    raise MCPError("invalid_response")
                return tools
            if not isinstance(cursor, str):
                raise MCPError("invalid_response")
        raise MCPError("response_too_large")


@asynccontextmanager
async def connect(server: dict):
    validate_server(server)
    try:
        # HTTPX builds its TLS trust store synchronously. Keep that disk I/O
        # off Home Assistant's event loop, even for optional discovery probes.
        client = await asyncio.to_thread(
            httpx.AsyncClient, follow_redirects=False, trust_env=False, timeout=10,
        )
        async with asyncio.timeout(TIMEOUT), client:
            connection = MCPConnection(server, client)
            try:
                initialized = await connection.rpc("initialize", {
                    "protocolVersion": PROTOCOL, "capabilities": {},
                    "clientInfo": {"name": "codex-assist", "version": "0.7.0"},
                })
                if initialized.get("protocolVersion") != PROTOCOL:
                    raise MCPError("unsupported_protocol")
                connection.headers["MCP-Protocol-Version"] = PROTOCOL
                await connection.rpc("notifications/initialized", notification=True)
                yield connection
            finally:
                if "Mcp-Session-Id" in connection.headers:
                    # Session cleanup failure must not hide a completed result.
                    try:
                        async with client.stream(
                            "DELETE", server["url"], headers=connection.headers, timeout=2,
                        ):
                            pass
                    except httpx.HTTPError:
                        pass
    except (httpx.HTTPError, TimeoutError, json.JSONDecodeError, UnicodeError):
        raise MCPError("connection_failed") from None


async def discover(server: dict) -> list[dict]:
    async with connect(server) as connection:
        return await connection.tools()
