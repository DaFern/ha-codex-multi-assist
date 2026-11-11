"""Real HA native schemas, request isolation, revocation and tool result types."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("homeassistant.components.llm", reason="MCP preview needs HA 2026.10+")

from homeassistant.core import Context
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

if not hasattr(llm, "ToolResult"):
    pytest.skip("MCP preview needs typed native results", allow_module_level=True)

from custom_components.codex_assist import mcp_tools as bridge
from custom_components.codex_assist.mcp_client import fingerprint

TOOL = {"name": "read_state", "description": "Read synthetic state",
        "inputSchema": {"type": "object", "properties": {"entity": {"type": "string"}},
                        "required": ["entity"], "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False}}


@pytest.fixture
def setup_bridge(hass, hass_admin_user, monkeypatch):
    server = {"id": "example", "url": "http://192.168.1.20/mcp", "enabled": True,
              "allow_local": True, "approved_tools": {TOOL["name"]: fingerprint(TOOL)}}
    entry = MockConfigEntry(domain="codex_assist", data={}, options={"mcp_servers": [server]})
    entry.add_to_hass(hass)
    context = Context(user_id=hass_admin_user.id)
    ctx = llm.LLMContext(platform="codex_assist", context=context, language="en",
                         assistant="conversation", device_id=None)
    remote = SimpleNamespace(tools=AsyncMock(return_value=[deepcopy(TOOL)]),
                             rpc=AsyncMock(return_value={"content": [
                                 {"type": "text", "text": "synthetic reading"}]}))

    @asynccontextmanager
    async def connect(_):
        yield remote

    monkeypatch.setattr(bridge, "connect", connect)
    monkeypatch.setattr(bridge, "discover", AsyncMock(return_value=[deepcopy(TOOL)]))
    return entry, server, ctx, remote


def call(tool):
    return llm.ToolInput(tool_name=tool.name, tool_args={"entity": "sensor.synthetic"})


async def test_native_read_only_schema_result_and_remote_errors(hass, setup_bridge):
    entry, server, ctx, remote = setup_bridge
    async with bridge.request_tools(hass, entry, ctx.context):
        tool, = bridge.tools_for_context(ctx.context)
        assert tool.name.startswith("codex_assist__mcp_")
        assert tool.annotations.read_only is True
        assert tool.parameters({"entity": "sensor.synthetic"}) == {"entity": "sensor.synthetic"}
        result = await tool.async_call(hass, call(tool), ctx)
        assert result.error is False
        assert "synthetic reading" in str(result.data)
        remote.rpc.assert_awaited_once_with("tools/call", {
            "name": "read_state", "arguments": {"entity": "sensor.synthetic"},
        })
        remote.rpc.return_value = {"content": [], "isError": True}
        assert (await tool.async_call(hass, call(tool), ctx)).error is True
    assert bridge.tools_for_context(ctx.context) == []


async def test_unknown_nonadmin_unbound_voice_and_inactive_user_never_discover(
    hass, setup_bridge, hass_read_only_user, monkeypatch,
):
    entry, _, ctx, _ = setup_bridge
    for context, voice in [(Context(), False), (Context(user_id="forged"), False),
                           (Context(user_id=hass_read_only_user.id), False), (ctx.context, True)]:
        async with bridge.request_tools(hass, entry, context, voice_packet=voice):
            assert bridge.tools_for_context(context) == []
    readonly_context = Context(user_id=hass_read_only_user.id)
    async with bridge.request_tools(
        hass, entry, readonly_context, voice_packet=True, voice_account_matches=True,
    ):
        assert bridge.tools_for_context(readonly_context) == []
    bridge.discover.assert_not_awaited()
    async with bridge.request_tools(
        hass, entry, ctx.context, voice_packet=True, voice_account_matches=True,
    ):
        tools = bridge.tools_for_context(ctx.context)
        assert len(tools) == 1
    bridge.discover.assert_awaited_once()
    monkeypatch.setattr(hass.auth, "async_get_user", AsyncMock(return_value=SimpleNamespace(
        is_active=False, is_admin=True, system_generated=False,
    )))
    async with bridge.request_tools(
        hass, entry, ctx.context, voice_packet=True, voice_account_matches=True,
    ):
        assert bridge.tools_for_context(ctx.context) == []


@pytest.mark.parametrize("change", ["disable", "remove", "schema", "account", "context"])
async def test_rechecks_at_invocation(hass, setup_bridge, monkeypatch, change):
    entry, server, ctx, remote = setup_bridge
    tool = bridge.MCPReadTool(entry, server, TOOL, ctx.context)
    if change == "disable":
        hass.config_entries.async_update_entry(entry, options={"mcp_servers": [
            {**server, "enabled": False},
        ]})
    elif change == "remove":
        await hass.config_entries.async_remove(entry.entry_id)
    elif change == "schema":
        remote.tools.return_value = [{**TOOL, "description": "new definition"}]
    elif change == "account":
        monkeypatch.setattr(hass.auth, "async_get_user", AsyncMock(return_value=None))
    else:
        ctx = SimpleNamespace(platform="codex_assist", assistant="conversation",
                              context=Context(user_id=ctx.context.user_id))
    assert (await tool.async_call(hass, call(tool), ctx)).error is True
    remote.rpc.assert_not_awaited()


async def test_account_revocation_during_discovery_and_bad_arguments(
    hass, setup_bridge, monkeypatch,
):
    entry, server, ctx, remote = setup_bridge
    tool = bridge.MCPReadTool(entry, server, TOOL, ctx.context)
    admin = SimpleNamespace(is_active=True, is_admin=True, system_generated=False)
    monkeypatch.setattr(hass.auth, "async_get_user", AsyncMock(side_effect=[admin, None]))
    assert (await tool.async_call(hass, call(tool), ctx)).error is True
    remote.rpc.assert_not_awaited()
    monkeypatch.setattr(hass.auth, "async_get_user", AsyncMock(return_value=admin))
    bad = llm.ToolInput(tool_name=tool.name, tool_args={"entity": 123, "user_id": "admin"})
    assert (await tool.async_call(hass, bad, ctx)).error is True
    remote.rpc.assert_not_awaited()


async def test_concurrent_requests_cannot_see_or_reuse_each_others_tools(hass, setup_bridge):
    entry, _, ctx, remote = setup_bridge
    other = Context(user_id=ctx.context.user_id)

    async def request(context):
        async with bridge.request_tools(hass, entry, context):
            await asyncio.sleep(0)
            assert len(bridge.tools_for_context(context)) == 1
            assert bridge.tools_for_context(other if context is ctx.context else ctx.context) == []

    await asyncio.gather(request(ctx.context), request(other))
    assert bridge.tools_for_context(ctx.context) == []
    remote.rpc.assert_not_awaited()
