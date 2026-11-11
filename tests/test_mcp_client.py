"""Synthetic transport contracts: never connect to a real server or home."""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from custom_components.codex_assist import mcp_client as mcp

TOOL = {"name": "read_state", "description": "Read synthetic state",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False}}


def server(**kwargs):
    return {"id": "test", "url": "http://192.168.1.20:9584/private_synthetic",
            "allow_local": True, "enabled": True, **kwargs}


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/mcp",
    "http://[fe80::1]/mcp", "http://0.0.0.0/mcp", "http://224.0.0.1/mcp",
    "http://example.com/mcp", "file:///mcp", "https://user:password@8.8.8.8/mcp",
    "https://8.8.8.8/mcp#fragment", "http://8.8.8.8/mcp", "https://100.64.0.1/mcp",
    "http://[::ffff:192.168.1.20]/mcp",
])
def test_rejects_ssrf_destinations(url):
    with pytest.raises(mcp.MCPError, match="invalid_endpoint"):
        mcp.validate_server(server(url=url))


def test_local_requires_opt_in_public_requires_tls():
    with pytest.raises(mcp.MCPError):
        mcp.validate_server(server(allow_local=False))
    mcp.validate_server(server())
    mcp.validate_server(server(url="https://8.8.8.8/mcp", allow_local=False))


@pytest.mark.parametrize("url", ["http://127.0.0.1:9584/private_synthetic",
                                  "http://[::1]:9584/private_synthetic"])
def test_loopback_has_its_own_explicit_opt_in(url):
    with pytest.raises(mcp.MCPError, match="invalid_endpoint"):
        mcp.validate_server(server(url=url))
    with pytest.raises(mcp.MCPError, match="invalid_endpoint"):
        mcp.validate_server(server(url=url, allow_local=True))
    mcp.validate_server(server(url=url, allow_loopback=True))
    mcp.validate_server(server(url=url.replace("http://", "https://"), allow_loopback=True))
    mcp.validate_server(server(url=url, allow_loopback=True, allow_local=False))


def test_default_deny_and_changed_definition_revokes_approval():
    config = server()
    assert not mcp.approved(config, TOOL)
    config["approved_tools"] = {TOOL["name"]: mcp.fingerprint(TOOL)}
    assert mcp.approved(config, TOOL)
    for key, value in [("description", "Changed"), ("inputSchema", {"type": "object"}),
                       ("annotations", {"readOnlyHint": False})]:
        changed = {**TOOL, key: value}
        assert not mcp.approved(config, changed)
    assert not mcp.approved({**config, "enabled": False}, TOOL)
    assert not mcp.eligible({**TOOL, "annotations": {}})
    assert not mcp.eligible({**TOOL, "annotations": {
        "readOnlyHint": True, "destructiveHint": True,
    }})


async def test_initialization_pagination_session_cleanup_and_no_retries(monkeypatch):
    calls = []

    def handle(request):
        assert request.headers["authorization"] == "Bearer synthetic-token"
        if request.method == "DELETE":
            calls.append("delete")
            return httpx.Response(204)
        body = json.loads(request.content)
        calls.append(body["method"])
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if body["method"] == "initialize":
            result = {"protocolVersion": mcp.PROTOCOL, "capabilities": {"tools": {}}}
        elif "cursor" not in body["params"]:
            assert request.headers["mcp-session-id"] == "synthetic-session"
            result = {"tools": [TOOL], "nextCursor": "page2"}
        else:
            result = {"tools": []}
        return httpx.Response(200, headers={"mcp-session-id": "synthetic-session"},
                              json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(mcp.httpx, "AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(handle), **kw,
    ))
    assert await mcp.discover(server(bearer_token="synthetic-token")) == [TOOL]
    assert calls == ["initialize", "notifications/initialized",
                     "tools/list", "tools/list", "delete"]


async def test_redirect_is_not_followed_and_error_is_redacted(monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": "http://127.0.0.1/private"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(mcp.httpx, "AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(handle), **kw,
    ))
    with pytest.raises(mcp.MCPError) as error:
        await mcp.discover(server())
    assert len(calls) == 1
    assert "private" not in str(error.value)


class Events(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n'
        raise AssertionError("must stop after the matching response, not wait for EOF")


async def test_sse_stops_at_complete_response():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=Events(),
    ))) as client:
        assert await mcp.MCPConnection(server(), client).rpc("tools/list") == {"tools": []}


@pytest.mark.parametrize("result", [
    {"jsonrpc": "2.0", "id": 99, "result": {}},
    {"jsonrpc": "2.0", "id": 1, "error": {"message": "private"}},
    [], {"jsonrpc": "2.0", "id": 1, "result": []},
])
async def test_invalid_rpc_is_not_success(result):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
        200, json=result,
    ))) as client:
        with pytest.raises(mcp.MCPError, match="invalid_response"):
            await mcp.MCPConnection(server(), client).rpc("tools/list")


async def test_response_bound_and_cancellation_propagation():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
        200, content=b"x" * (mcp.MAX_BYTES + 1), headers={"content-type": "application/json"},
    ))) as client:
        with pytest.raises(mcp.MCPError, match="response_too_large"):
            await mcp.MCPConnection(server(), client).rpc("tools/call")
    tool = deepcopy(TOOL)
    tool["name"] = "write"
    assert not mcp.approved(server(), tool)

    async def cancelled(_):
        raise asyncio.CancelledError

    async with httpx.AsyncClient(transport=httpx.MockTransport(cancelled)) as client:
        with pytest.raises(asyncio.CancelledError):
            await mcp.MCPConnection(server(), client).rpc("tools/list")


async def test_discovery_response_has_separate_larger_bound():
    discovery = {"tools": [], "metadata": "x" * (mcp.MAX_BYTES + 1)}

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": 1, "result": discovery},
    ))) as client:
        assert await mcp.MCPConnection(server(), client).rpc("tools/list") == discovery

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": 1, "result": {
            "content": [{"type": "text", "text": "x" * (mcp.MAX_BYTES + 1)}],
        }},
    ))) as client:
        with pytest.raises(mcp.MCPError, match="response_too_large"):
            await mcp.MCPConnection(server(), client).rpc("tools/call")


@pytest.mark.parametrize("result", [
    {}, {"content": [42]}, {"content": [{"type": "text"}]},
    {"content": [], "isError": "false"}, {"content": [], "structuredContent": []},
    {"content": [{"type": "image", "data": "x"}]},
    {"content": [{"type": "resource", "resource": {"uri": "synthetic:"}}]},
])
def test_malformed_tool_result_is_never_success(result):
    with pytest.raises(mcp.MCPError):
        mcp.validate_result(result)
