"""Explicit learning pairing and phone opt-in, without Codex authentication."""

import voluptuous as vol
from cryptography.fernet import Fernet
from homeassistant import config_entries
from homeassistant.helpers import selector

from .. import DOMAIN
from ..entry_modules import CONF_MODULE, EntryModule, learning_supported
from .bridge_client import BridgeClient, validate_url
from .const import CONF_CONTROL_STT, CONF_PHONE_ENABLED
from .learning_bridge_protocol import BridgeError


def phone_schema(defaults):
    fields = {
        vol.Required(CONF_PHONE_ENABLED, default=defaults.get(CONF_PHONE_ENABLED, False)): bool
    }
    source = defaults.get(CONF_CONTROL_STT)
    key = (
        vol.Optional(CONF_CONTROL_STT, default=source) if source else vol.Optional(CONF_CONTROL_STT)
    )
    fields[key] = selector.EntitySelector({"domain": "stt", "integration": "wyoming"})
    return vol.Schema(fields)


def phone_options(hass, user_input, defaults):
    options = {**defaults, **user_input}
    if options.get(CONF_PHONE_ENABLED, False):
        from .stt import control_source

        control_source(hass, options.get(CONF_CONTROL_STT))
    return options


class LearningConfigFlowMixin:
    async def async_step_voice_learning(self, user_input=None):
        if not learning_supported():
            return self.async_abort(reason="learning_requires_current_ha")
        reconfigure = self.source == config_entries.SOURCE_RECONFIGURE
        existing = self._get_reconfigure_entry() if reconfigure else None
        if not reconfigure:
            await self.async_set_unique_id(DOMAIN + ":voice_match")
            self._abort_if_unique_id_configured()
        saved = existing.data if existing else {}
        errors = {}
        if user_input is not None:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession

            try:
                url = validate_url(user_input["url"])
                key = user_input.get("key", "").strip() or saved.get("key", "")
                Fernet(key)
                bridge = BridgeClient(url, key, async_get_clientsession(self.hass))
                if await bridge.call("hello", None, {}) != {"ready": True}:
                    raise BridgeError("Learning bridge unavailable")
            except ValueError, TypeError, BridgeError:
                errors["base"] = "cannot_connect"
            else:
                data = {CONF_MODULE: EntryModule.VOICE_MATCH.value, "url": url, "key": key}
                if reconfigure:
                    return self.async_update_reload_and_abort(existing, data_updates=data)
                self._learning_setup_data = data
                return await self.async_step_learning_phone()
        url_field = vol.Required("url", default=saved["url"]) if saved else vol.Required("url")
        key_field = vol.Optional("key") if saved else vol.Required("key")
        return self.async_show_form(
            step_id="voice_learning",
            errors=errors,
            data_schema=vol.Schema(
                {
                    url_field: str,
                    key_field: selector.TextSelector(selector.TextSelectorConfig(type="password")),
                }
            ),
        )

    async def async_step_learning_phone(self, user_input=None):
        if not learning_supported():
            return self.async_abort(reason="learning_requires_current_ha")
        errors = {}
        if user_input is not None:
            try:
                options = phone_options(self.hass, user_input, {})
            except ValueError:
                errors["base"] = "invalid_stt_source"
            else:
                return self.async_create_entry(
                    title="Voice Match learning", data=self._learning_setup_data, options=options
                )
        return self.async_show_form(
            step_id="learning_phone", errors=errors, data_schema=phone_schema({})
        )


class LearningOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if not learning_supported():
            return self.async_abort(reason="learning_requires_current_ha")
        return await self.async_step_learning_phone(user_input)

    async def async_step_learning_phone(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                options = phone_options(self.hass, user_input, self.config_entry.options)
            except ValueError:
                errors["base"] = "invalid_stt_source"
            else:
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="learning_phone",
            errors=errors,
            data_schema=phone_schema(self.config_entry.options),
        )
