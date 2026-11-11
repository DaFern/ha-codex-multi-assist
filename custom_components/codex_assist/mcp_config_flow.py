"""Administrator setup and explicit definition-bound read-only tool approval."""

from copy import deepcopy

import voluptuous as vol
from homeassistant.helpers import selector

from .entry_modules import learning_supported
from .mcp_client import (
    CONF_MCP_SERVERS,
    MCPError,
    discover,
    eligible,
    fingerprint,
    validate_server,
)


class MCPOptionsMixin:
    _mcp_id = None
    _mcp_candidate = None
    _mcp_discovered = None

    async def async_step_mcp(self, user_input=None):
        if not learning_supported():
            return self.async_abort(reason="mcp_requires_current_ha")
        return self.async_show_menu(
            step_id="mcp", menu_options=["mcp_add", "mcp_edit", "init"],
        )

    async def async_step_mcp_add(self, user_input=None):
        self._mcp_id = None
        return await self.async_step_mcp_server()

    async def async_step_mcp_edit(self, user_input=None):
        servers = self.config_entry.options.get(CONF_MCP_SERVERS, [])
        if not servers:
            return await self.async_step_mcp_add()
        if user_input is not None:
            self._mcp_id = user_input["server_id"]
            return await self.async_step_mcp_server()
        return self.async_show_form(step_id="mcp_edit", data_schema=vol.Schema({
            vol.Required("server_id"): vol.In([s["id"] for s in servers]),
        }))

    async def async_step_mcp_server(self, user_input=None):
        servers = self.config_entry.options.get(CONF_MCP_SERVERS, [])
        saved = next((s for s in servers if s["id"] == self._mcp_id), {})
        defaults = saved
        errors = {}
        if user_input is not None:
            candidate = deepcopy(user_input)
            defaults = candidate
            candidate["allow_loopback"] = bool(candidate.get("allow_loopback", False))
            candidate["bearer_token"] = candidate.get("bearer_token", "").strip()
            if not candidate["bearer_token"] and not candidate.pop("clear_token", False):
                candidate["bearer_token"] = saved.get("bearer_token", "")
            candidate.pop("clear_token", None)
            candidate["approved_tools"] = {}
            try:
                validate_server(candidate)
                if (candidate["id"] != self._mcp_id
                        and any(s["id"] == candidate["id"] for s in servers)):
                    raise MCPError("invalid_server")
                if not saved and len(servers) >= 8:
                    raise MCPError("invalid_server")
                self._mcp_candidate = candidate
                if not candidate["enabled"]:
                    return self._save_mcp()
                self._mcp_discovered = [t for t in await discover(candidate) if eligible(t)]
                return await self.async_step_mcp_tools()
            except MCPError as err:
                errors["base"] = str(err)
        return self.async_show_form(step_id="mcp_server", errors=errors, data_schema=vol.Schema({
            vol.Required("id", default=defaults.get("id", "")): str,
            vol.Required("url", default=defaults.get("url", "")): str,
            vol.Required("enabled", default=defaults.get("enabled", False)): bool,
            vol.Required("allow_local", default=defaults.get("allow_local", False)): bool,
            vol.Required(
                "allow_loopback", default=defaults.get("allow_loopback", False),
            ): bool,
            vol.Optional("bearer_token"): selector.TextSelector(
                selector.TextSelectorConfig(type="password")),
            vol.Required("clear_token", default=False): bool,
        }))

    async def async_step_mcp_tools(self, user_input=None):
        tools = {t["name"]: t for t in self._mcp_discovered or []}
        errors = {}
        if user_input is not None:
            selected = user_input.get("tools", [])
            if not set(selected) <= tools.keys() or user_input.get("confirm_read_only") is not True:
                errors["base"] = "mcp_approval_required"
            else:
                self._mcp_candidate["approved_tools"] = {
                    name: fingerprint(tools[name]) for name in selected
                }
                return self._save_mcp()
        return self.async_show_form(
            step_id="mcp_tools", errors=errors,
            description_placeholders={"tool_count": str(len(tools))},
            data_schema=vol.Schema({
                vol.Required("tools", default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(tools), multiple=True)),
                vol.Required("confirm_read_only", default=False): bool,
            }),
        )

    def _save_mcp(self):
        servers = [s for s in self.config_entry.options.get(CONF_MCP_SERVERS, [])
                   if s["id"] != self._mcp_id]
        servers.append(self._mcp_candidate)
        return self.async_create_entry(title="", data={
            **self.config_entry.options, CONF_MCP_SERVERS: servers,
        })
