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
        if (
            not saved
            and user_input is None
            and not getattr(self, "_learning_discovery_done", False)
        ):
            from .discovery import suggested_origins

            hass = getattr(self, "hass", None)
            self._learning_origins = suggested_origins(hass) if hass is not None else []
            if self._learning_origins:
                return await self.async_step_learning_discovery()
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
        origin = saved.get("url") or getattr(self, "_learning_selected_url", None)
        url_field = vol.Required("url", default=origin) if origin else vol.Required("url")
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

    async def async_step_learning_discovery(self, user_input=None):
        errors = {}
        origins = getattr(self, "_learning_origins", [])
        if user_input is not None:
            chosen = user_input.get("origin")
            if chosen == "manual" or chosen in origins:
                self._learning_selected_url = None if chosen == "manual" else chosen
                self._learning_discovery_done = True
                return await self.async_step_voice_learning()
            errors["base"] = "invalid_origin"
        return self.async_show_form(
            step_id="learning_discovery",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("origin"): selector.SelectSelector(
                        {
                            "options": [
                                *({"value": origin, "label": origin} for origin in origins),
                                {"value": "manual", "label": "Enter manually"},
                            ],
                        }
                    )
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
                self._learning_phone_options = options
                return await self.async_step_learning_finish()
        return self.async_show_form(
            step_id="learning_phone", errors=errors, data_schema=phone_schema({})
        )

    async def async_step_learning_finish(self, user_input=None):
        if not hasattr(self, "_learning_setup_data") or not hasattr(
            self, "_learning_phone_options"
        ):
            return self.async_abort(reason="learning_setup_required")
        if user_input is not None:
            return self.async_create_entry(
                title="Voice Match learning",
                data=self._learning_setup_data,
                options=self._learning_phone_options,
            )
        enabled = self._learning_phone_options.get(CONF_PHONE_ENABLED, False)
        return self.async_show_form(
            step_id="learning_finish",
            data_schema=vol.Schema({}),
            description_placeholders={"phone_status": "Enabled" if enabled else "Off"},
        )


class LearningOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if not learning_supported():
            return self.async_abort(reason="learning_requires_current_ha")
        return self.async_show_menu(
            step_id="learning_menu",
            menu_options=[
                "learning_status",
                "learning_phone",
                "learning_pairing",
                "learning_personalisation",
            ],
        )

    async def async_step_learning_menu(self, user_input=None):
        return await self.async_step_init(user_input)

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

    async def async_step_learning_status(self, user_input=None):
        if user_input is not None and not user_input.get("recheck", False):
            return await self.async_step_init()
        from .readiness import async_check_setup

        report = await async_check_setup(self.hass, self.config_entry)
        labels = {
            "verified": "Encrypted pairing verified now",
            "available": "Provider and language available; confirm this is ordinary Whisper",
            "ready": "Technical check passed",
            "disabled": "Off by choice",
            "not_required": "Not required while phone learning is off",
            "unavailable": "Unavailable; needs attention",
            "not_loaded": "Learning entry is not loaded",
            "missing": "Not configured",
            "ambiguous": "More than one matching assistant; choose exactly one",
            "mismatch": "Assistant engines do not match the learning pair",
            "conflict": "Launcher address belongs to another panel",
            "not_checked": "Not checked; configuration may have changed",
        }
        return self.async_show_form(
            step_id="learning_status",
            data_schema=vol.Schema({vol.Required("recheck", default=False): bool}),
            description_placeholders={key: labels[value] for key, value in report.items()},
        )

    async def async_step_learning_pairing(self, user_input=None):
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(step_id="learning_pairing", data_schema=vol.Schema({}))

    async def async_step_learning_personalisation(self, user_input=None):
        targets = {
            entry.entry_id: entry
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get(CONF_MODULE, EntryModule.CODEX) == EntryModule.CODEX
            and entry.disabled_by is None
        }
        if not targets:
            return self.async_show_form(
                step_id="learning_personalisation_missing", data_schema=vol.Schema({})
            )
        errors = {}
        if user_input is not None:
            target = targets.get(user_input.get("entry_id"))
            if target is not None:
                self._personalisation_target = target.entry_id
                return await self.async_step_learning_personalisation_guide()
            errors["base"] = "invalid_target"
        return self.async_show_form(
            step_id="learning_personalisation",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("entry_id"): selector.SelectSelector(
                        {
                            "options": [
                                {"value": key, "label": entry.title}
                                for key, entry in targets.items()
                            ]
                        }
                    )
                }
            ),
        )

    async def async_step_learning_personalisation_missing(self, user_input=None):
        return await self.async_step_init()

    async def async_step_learning_personalisation_guide(self, user_input=None):
        if user_input is not None:
            return await self.async_step_init()
        from ..voice_match import CONF_VOICE_MATCH_KEY

        target = self.hass.config_entries.async_get_entry(self._personalisation_target)
        if (
            target is None
            or target.domain != DOMAIN
            or target.disabled_by is not None
            or target.data.get(CONF_MODULE, EntryModule.CODEX) != EntryModule.CODEX
        ):
            return await self.async_step_learning_personalisation()
        status = (
            "Configured on the selected Codex entry; not verified by this check"
            if target.options.get(CONF_VOICE_MATCH_KEY)
            else "Not configured"
        )
        return self.async_show_form(
            step_id="learning_personalisation_guide",
            data_schema=vol.Schema({}),
            description_placeholders={"pairing_status": status},
        )
