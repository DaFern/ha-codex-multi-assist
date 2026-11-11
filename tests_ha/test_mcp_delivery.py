"""Native Assist → Codex → authorized MCP → native tool-result replay."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("homeassistant.components.llm", reason="MCP preview needs HA 2026.10+")

from homeassistant.components import conversation
from homeassistant.core import Context
from homeassistant.helpers import llm
from test_clarification_followups import clarification_entry as clarification_entry
from test_web_search_delivery import COMPLETED, call_event, model_round, text_events
from test_web_search_delivery import backend as backend

if not hasattr(llm, "ToolResult"):
    pytest.skip("MCP preview needs typed native results", allow_module_level=True)

from custom_components.codex_assist import mcp_tools as bridge
from custom_components.codex_assist.mcp_client import fingerprint

TOOL = {"name": "read_example", "description": "Read a synthetic example.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False}}
SERVER = {"id": "example", "url": "http://192.168.1.20/mcp", "enabled": True,
          "allow_local": True, "approved_tools": {TOOL["name"]: fingerprint(TOOL)}}


@pytest.fixture
def entry_settings():
    return {}, {"mcp_servers": [SERVER], "agents": [
        {"id": "primary", "name": "First reader", "prompt": "Be concise."},
        {"id": "second", "name": "Second reader", "prompt": "Be concise."},
    ]}


@pytest.fixture
def web_search():
    return False


async def test_native_tool_delivery_for_both_agents(
    hass, clarification_entry, backend, hass_admin_user, hass_read_only_user, monkeypatch,
):
    rpc = AsyncMock(return_value={"content": [{"type": "text", "text": "synthetic reading 42"}]})

    @asynccontextmanager
    async def connect(_):
        from types import SimpleNamespace

        yield SimpleNamespace(tools=AsyncMock(return_value=[TOOL]), rpc=rpc)

    monkeypatch.setattr(bridge, "connect", connect)
    monkeypatch.setattr(bridge, "discover", AsyncMock(return_value=[TOOL]))
    planned, requests = backend
    tool = bridge.MCPReadTool(clarification_entry, SERVER, TOOL, Context())
    agents = [s.entity_id for s in hass.states.async_all("conversation")
              if s.entity_id != "conversation.home_assistant"]
    assert len(agents) == 2
    for index, agent in enumerate(agents):
        model_round(planned, [call_event(f"mcp-{index}", tool.name, {}), COMPLETED])
        model_round(planned, text_events("The reading is 42.") + [COMPLETED])
        result = await conversation.async_converse(
            hass, "Read the synthetic MCP example", None, Context(user_id=hass_admin_user.id),
            language="en", agent_id=agent,
        )
        assert result.response.speech["plain"]["speech"] == "The reading is 42."
        payloads = [payload for path, payload in requests if path.endswith("/responses")]
        assert any(t["name"] == tool.name for t in payloads[-2]["tools"])
        assert "synthetic reading 42" in str(payloads[-1]["input"])
    assert rpc.await_count == 2
    assert not planned
    previous_id = result.conversation_id
    model_round(planned, text_events("It was 42.") + [COMPLETED])
    followup = await conversation.async_converse(
        hass, "What was the reading?", previous_id, Context(user_id=hass_admin_user.id),
        language="en", agent_id=agents[-1],
    )
    assert followup.conversation_id == previous_id
    payloads = [payload for path, payload in requests if path.endswith("/responses")]
    assert "synthetic reading 42" in str(payloads[-1]["input"])

    for context in [Context(), Context(user_id=hass_read_only_user.id)]:
        model_round(planned, text_events("This is a fresh conversation.") + [COMPLETED])
        other = await conversation.async_converse(
            hass, "Read the previous result", previous_id, context,
            language="en", agent_id=agents[-1],
        )
        assert other.conversation_id != previous_id
        payloads = [payload for path, payload in requests if path.endswith("/responses")]
        assert "synthetic reading 42" not in str(payloads[-1]["input"])
        assert not any(t["name"] == tool.name for t in payloads[-1]["tools"])
    assert rpc.await_count == 2
