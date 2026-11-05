"""Explicit repair guidance; no automatic key, pipeline or recording mutations."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.repairs import FlowType, RepairsFlow

from . import DOMAIN
from .entry_modules import EntryModule, learning_supported
from .learning.health_issues import KINDS
from .learning.health_issues import issue_id as learning_issue_id


class LearningRepairFlow(RepairsFlow):
    def target_entry(self):
        data = self.data or {}
        entry = self.hass.config_entries.async_get_entry(data.get("entry_id", ""))
        kind = data.get("kind")
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.disabled_by is not None
            or entry.data.get("module") != EntryModule.VOICE_MATCH
            or kind not in KINDS
            or self.issue_id != learning_issue_id(entry.entry_id, kind)
        ):
            return None
        return entry

    async def async_step_init(self, user_input=None):
        if not learning_supported() or self.target_entry() is None:
            return self.async_abort(reason="learning_entry_unavailable")
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        entry = self.target_entry()
        if entry is None:
            return self.async_abort(reason="learning_entry_unavailable")
        if user_input is not None:
            if self.data["kind"] == "bridge":
                result = await self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={
                        "source": config_entries.SOURCE_RECONFIGURE,
                        "entry_id": entry.entry_id,
                    },
                )
                return self.async_abort(
                    reason="learning_reconfigure",
                    next_flow=(FlowType.CONFIG_FLOW, result["flow_id"]),
                )
            if self.data["kind"] == "source":
                result = await self.hass.config_entries.options.async_init(entry.entry_id)
                return self.async_abort(
                    reason="learning_options", next_flow=(FlowType.OPTIONS_FLOW, result["flow_id"])
                )
            return await self.async_step_check()
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))

    async def async_step_check(self, user_input=None):
        entry = self.target_entry()
        if entry is None:
            return self.async_abort(reason="learning_entry_unavailable")
        errors = {}
        if user_input is not None:
            from .learning.health_issues import RESOLVED
            from .learning.readiness import async_check_setup

            report = await async_check_setup(self.hass, entry)
            if report[self.data["kind"]] in RESOLVED:
                return self.async_create_entry(data={})
            errors["base"] = "not_resolved"
        return self.async_show_form(step_id="check", data_schema=vol.Schema({}), errors=errors)


async def async_create_fix_flow(hass, issue_id, data):
    return LearningRepairFlow()
