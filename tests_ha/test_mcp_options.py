"""Supported HA options API saves credentials without exposing saved defaults."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist.entry_modules import learning_supported
from custom_components.codex_assist.mcp_client import MCPError, fingerprint

TOOL = {"name": "read_example", "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True}}
SERVER = {"id": "example", "url": "http://192.168.1.20/mcp", "enabled": True,
          "allow_local": True, "bearer_token": "synthetic-private-token", "clear_token": False}


async def start(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "mcp"},
    )


async def test_mcp_menu_is_version_gated(hass):
    entry = MockConfigEntry(domain="codex_assist", data={})
    entry.add_to_hass(hass)
    result = await start(hass, entry)
    if learning_supported():
        assert result["type"] == "menu"
    else:
        assert result["type"] == "abort"
        assert result["reason"] == "mcp_requires_current_ha"


async def test_probe_approve_disable_and_preserve_unrelated_options(hass, monkeypatch):
    if not learning_supported():
        pytest.skip("MCP preview requires HA 2026.10+")
    entry = MockConfigEntry(domain="codex_assist", data={}, options={"prompt": "keep me"})
    entry.add_to_hass(hass)
    probe = AsyncMock(return_value=[TOOL, {**TOOL, "name": "write", "annotations": {}}])
    monkeypatch.setattr("custom_components.codex_assist.mcp_config_flow.discover", probe)
    result = await start(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "mcp_add"},
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], SERVER)
    assert result["step_id"] == "mcp_tools"
    assert result["description_placeholders"]["tool_count"] == "1"
    assert "mcp_servers" not in entry.options
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "tools": ["read_example"], "confirm_read_only": False,
    })
    assert result["errors"]["base"] == "mcp_approval_required"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "tools": ["read_example"], "confirm_read_only": True,
    })
    assert result["type"] == "create_entry"
    assert entry.options["prompt"] == "keep me"
    saved, = entry.options["mcp_servers"]
    assert saved["approved_tools"] == {"read_example": fingerprint(TOOL)}
    assert saved["bearer_token"] == "synthetic-private-token"
    probe.assert_awaited_once()

    result = await start(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "mcp_edit"},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"server_id": "example"},
    )
    assert "synthetic-private-token" not in repr(result)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**SERVER, "bearer_token": "", "enabled": False},
    )
    assert result["type"] == "create_entry"
    assert entry.options["mcp_servers"][0]["enabled"] is False
    assert entry.options["mcp_servers"][0]["approved_tools"] == {}
    assert entry.options["mcp_servers"][0]["bearer_token"] == "synthetic-private-token"
    probe.assert_awaited_once()


async def test_failed_discovery_never_saves_config_or_exposes_secrets(hass, monkeypatch):
    if not learning_supported():
        pytest.skip("MCP preview requires HA 2026.10+")
    entry = MockConfigEntry(domain="codex_assist", data={}, options={"prompt": "keep me"})
    entry.add_to_hass(hass)
    original = deepcopy(dict(entry.options))
    monkeypatch.setattr("custom_components.codex_assist.mcp_config_flow.discover",
                        AsyncMock(side_effect=MCPError("connection_failed")))
    result = await start(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "mcp_add"},
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], SERVER)
    assert result["errors"]["base"] == "connection_failed"
    assert "synthetic-private-token" not in repr(result)
    assert dict(entry.options) == original
