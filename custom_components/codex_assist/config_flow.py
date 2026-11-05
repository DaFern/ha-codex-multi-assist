from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.helpers.httpx_client import get_async_client

from . import DOMAIN
from .agent_profiles import (
    CONF_AGENTS,
    AgentProfile,
    get_agent_profiles,
)
from .codex_auth import (
    CODEX_DEVICE_VERIFICATION_URL,
    CodexAuthClient,
    CodexDeviceCode,
)
from .codex_image import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_IMAGE_SIZE,
    IMAGE_MODEL_QUALITY,
    IMAGE_SIZE_OPTIONS,
)
from .codex_models import ModelCatalog, ModelDiscoveryCache, fetch_codex_model_ids
from .codex_runtime import runtime_token_coordinator
from .entry_modules import CONF_MODULE, EntryModule, entry_module
from .learning.config_flow import LearningConfigFlowMixin, LearningOptionsFlow
from .model_discovery import async_entry_model_catalog
from .speaker_packet import valid_key
from .voice_match import CONF_VOICE_MATCH_KEY

CONF_ACCESS_TOKEN = "access_token"
CONF_PROMPT = "prompt"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_MODEL = "model"
CONF_IMAGE_MODEL = "image_model"
CONF_IMAGE_SIZE = "image_size"
CONF_REASONING_EFFORT = "reasoning_effort"
CONF_REASONING_SUMMARY = "reasoning_summary"
CONF_TEXT_VERBOSITY = "text_verbosity"
CONF_WEB_SEARCH = "web_search"
SECTION_CHAT_SETTINGS = "chat_settings"
SECTION_ADVANCED_SETTINGS = "advanced_settings"
SECTION_IMAGE_SETTINGS = "image_settings"
DEFAULT_PROMPT = "You are a concise Home Assistant Assist conversation agent."
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_REASONING_SUMMARY = "auto"
DEFAULT_TEXT_VERBOSITY = "medium"
DEFAULT_WEB_SEARCH = False


class CodexAssistConfigFlow(LearningConfigFlowMixin, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CodexAssistOptionsFlow | LearningOptionsFlow:
        if entry_module(config_entry) is EntryModule.VOICE_MATCH:
            return LearningOptionsFlow()
        return CodexAssistOptionsFlow()

    def __init__(self) -> None:
        self._setup_input: dict[str, Any] = {}
        self._device_code: CodexDeviceCode | None = None
        self._setup_data: dict[str, Any] = {}
        self._model_cache = ModelDiscoveryCache()
        self._catalog: ModelCatalog | None = None

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(step_id="user", menu_options=["codex", "voice_learning"])

    async def async_step_codex(self, user_input=None):
        if any(
            entry.data.get(CONF_MODULE, EntryModule.CODEX) == EntryModule.CODEX
            for entry in self._async_current_entries()
        ):
            return self.async_abort(reason="already_configured")
        if user_input is not None:
            self._setup_input = {}
            try:
                self._device_code = await self._auth_client().request_device_code()
            except RuntimeError:
                return self.async_show_form(
                    step_id="codex",
                    data_schema=_user_schema(),
                    errors={"base": "device_code_request_failed"},
                )
            return await self.async_step_device()

        return self.async_show_form(step_id="codex", data_schema=_user_schema())

    async def async_step_device(self, user_input=None):
        if user_input is not None:
            return await self.async_step_device_wait()
        return self._show_device_form()

    async def async_step_device_wait(self, user_input=None):
        del user_input
        if self._device_code is None:
            return await self.async_step_codex()

        auth_client = self._auth_client()
        try:
            authorization = await auth_client.poll_device_code(
                device_auth_id=self._device_code.device_auth_id,
                user_code=self._device_code.user_code,
            )
            if authorization is None:
                return self._show_device_form(errors={"base": "authorization_pending"})
            tokens = await auth_client.exchange_authorization_code(authorization)
        except RuntimeError:
            return self._show_device_form(errors={"base": "device_code_auth_failed"})

        data = {
            **self._setup_input,
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
        }
        if self.source == config_entries.SOURCE_REAUTH:
            _clear_model_cache(self._get_reauth_entry())
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data_updates=data,
            )
        if self.source == config_entries.SOURCE_RECONFIGURE:
            _clear_model_cache(self._get_reconfigure_entry())
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data_updates=data,
            )

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        self._setup_data = {**data, CONF_MODULE: EntryModule.CODEX.value}
        return await self.async_step_model()

    async def async_step_model(self, user_input=None):
        errors = {}
        if user_input is not None and self._catalog and self._catalog.models:
            model = user_input.get(CONF_MODEL)
            if model in self._catalog.models:
                return self.async_create_entry(
                    title="Codex Assist", data={**self._setup_data, CONF_MODEL: model}
                )
            errors["base"] = "invalid_model"
        if self._catalog is None or not self._catalog.models:
            self._catalog = await self._model_cache.async_get(
                lambda: fetch_codex_model_ids(
                    http_client=get_async_client(self.hass),
                    access_token=self._setup_data.get(CONF_ACCESS_TOKEN),
                ),
                force=True,
            )
        if not self._catalog.models:
            errors["base"] = "no_models"
        return self.async_show_form(
            step_id="model",
            data_schema=_model_schema({}, model_options=list(self._catalog.models)),
            errors=errors,
            description_placeholders={"model_status": _catalog_description(self._catalog)},
        )

    async def async_step_reconfigure(self, user_input=None):
        if entry_module(self._get_reconfigure_entry()) is not EntryModule.CODEX:
            return await self.async_step_voice_learning(user_input)
        if user_input is not None:
            self._setup_input = {}
            try:
                self._device_code = await self._auth_client().request_device_code()
            except RuntimeError:
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=vol.Schema({}),
                    errors={"base": "device_code_request_failed"},
                )
            return await self.async_step_device()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({}),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]):
        if entry_data.get(CONF_MODULE, EntryModule.CODEX) != EntryModule.CODEX:
            return self.async_abort(reason="learning_reconfigure_required")
        self._setup_input = {
            key: entry_data[key]
            for key in (
                CONF_MODEL,
                CONF_IMAGE_MODEL,
                CONF_IMAGE_SIZE,
                CONF_PROMPT,
                CONF_REASONING_EFFORT,
                CONF_REASONING_SUMMARY,
                CONF_TEXT_VERBOSITY,
                CONF_WEB_SEARCH,
            )
            if key in entry_data
        }
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        try:
            self._device_code = await self._auth_client().request_device_code()
        except RuntimeError:
            return self.async_show_form(
                step_id="reauth_confirm",
                errors={"base": "device_code_request_failed"},
            )
        return await self.async_step_device()

    def _auth_client(self) -> CodexAuthClient:
        return CodexAuthClient(http_client=get_async_client(self.hass))

    def _show_device_form(self, errors=None):
        device_code = self._device_code
        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "verification_uri": CODEX_DEVICE_VERIFICATION_URL,
                "user_code": device_code.user_code if device_code else "",
                "interval": str(device_code.interval) if device_code else "5",
            },
        )


def _user_schema() -> vol.Schema:
    return vol.Schema({})


def _clear_model_cache(entry) -> None:
    runtime_token_coordinator(entry).model_cache.clear()


class CodexAssistOptionsFlow(config_entries.OptionsFlow):
    def __init__(self) -> None:
        self._catalog: ModelCatalog | None = None
        self._agents: list[dict[str, Any]] | None = None
        self._editing_agent_id: str | None = None
        self._removing_agent_id: str | None = None

    async def async_step_init(self, user_input=None):
        if entry_module(self.config_entry) is not EntryModule.CODEX:
            return self.async_abort(reason="learning_reconfigure_required")
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "agents", "voice_match"],
        )

    async def async_step_voice_match(self, user_input=None):
        saved = self.config_entry.options.get(CONF_VOICE_MATCH_KEY, "")
        errors = {}
        if user_input is not None:
            options = dict(self.config_entry.options)
            if not user_input.get("enabled"):
                options.pop(CONF_VOICE_MATCH_KEY, None)
                return self.async_create_entry(title="", data=options)
            key = user_input.get(CONF_VOICE_MATCH_KEY, "").strip() or saved
            if valid_key(key):
                options[CONF_VOICE_MATCH_KEY] = key
                return self.async_create_entry(title="", data=options)
            errors["base"] = "invalid_voice_match_pairing_key"
        return self.async_show_form(
            step_id="voice_match",
            data_schema=vol.Schema({
                vol.Required("enabled", default=bool(saved)): bool,
                # Deliberately no saved/default key in the form payload.
                vol.Optional(CONF_VOICE_MATCH_KEY): selector.TextSelector(
                    selector.TextSelectorConfig(type="password")
                ),
            }),
            errors=errors,
        )

    async def async_step_settings(self, user_input=None):
        defaults = {**self.config_entry.data, **self.config_entry.options}
        errors = {}
        if user_input is not None:
            data = _flatten_settings_input(user_input)
            model = data.get(CONF_MODEL, defaults.get(CONF_MODEL))
            if (
                self._catalog is not None
                and model not in self._catalog.models
                and model != defaults.get(CONF_MODEL)
            ):
                errors["base"] = "invalid_model"
            else:
                if model is not None:
                    data[CONF_MODEL] = model
                if CONF_REASONING_SUMMARY in defaults:
                    data[CONF_REASONING_SUMMARY] = defaults[CONF_REASONING_SUMMARY]
                return self.async_create_entry(
                    title="",
                    data={**self.config_entry.options, **data},
                )

        if self._catalog is None:
            self._catalog = await async_entry_model_catalog(
                self.hass, self.config_entry, force=True
            )
        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(defaults, model_options=list(self._catalog.models)),
            errors=errors,
            description_placeholders={
                "model_status": _catalog_description(self._catalog, defaults.get(CONF_MODEL))
            },
        )

    async def async_step_agents(self, user_input=None):
        self._agents = [profile.as_dict() for profile in get_agent_profiles(self.config_entry)]
        return self.async_show_menu(
            step_id="agents",
            menu_options=["add_agent", "edit_agent", "remove_agent", "init"],
        )

    async def async_step_add_agent(self, user_input=None):
        profile = _new_profile_defaults(self.config_entry)
        if user_input is not None:
            error = _validate_agent_input(
                user_input,
                self._agent_profiles(),
                allowed_models=await self._model_options(),
            )
            if error:
                return self.async_show_form(
                    step_id="add_agent",
                    data_schema=_agent_profile_schema(profile, await self._model_options()),
                    errors={"base": error},
                )
            self._agent_profiles().append(
                _profile_from_input(uuid4().hex, user_input).as_dict()
            )
            return self._save_agents()
        return self.async_show_form(
            step_id="add_agent",
            data_schema=_agent_profile_schema(profile, await self._model_options()),
        )

    async def async_step_edit_agent(self, user_input=None):
        profiles = self._agent_profiles()
        if not profiles:
            return self.async_show_menu(step_id="agents", menu_options=["add_agent", "init"])
        if user_input is not None:
            self._editing_agent_id = user_input.get("agent_id")
            return await self.async_step_edit_agent_settings()
        return self.async_show_form(
            step_id="edit_agent",
            data_schema=_agent_choice_schema(profiles),
        )

    async def async_step_edit_agent_settings(self, user_input=None):
        profiles = self._agent_profiles()
        profile_data = next(
            (item for item in profiles if item["id"] == self._editing_agent_id),
            None,
        )
        if profile_data is None:
            return self.async_show_menu(
                step_id="agents",
                menu_options=["add_agent", "edit_agent", "remove_agent", "init"],
            )
        profile = _profile_from_dict(profile_data)
        if user_input is not None:
            other_profiles = [item for item in profiles if item["id"] != profile.agent_id]
            error = _validate_agent_input(
                user_input,
                other_profiles,
                allowed_models=await self._model_options(),
                saved_model=profile.model,
            )
            if error:
                return self.async_show_form(
                    step_id="edit_agent_settings",
                    data_schema=_agent_profile_schema(profile, await self._model_options()),
                    errors={"base": error},
                )
            replacement = _profile_from_input(profile.agent_id, user_input).as_dict()
            profiles[profiles.index(profile_data)] = replacement
            return self._save_agents()
        return self.async_show_form(
            step_id="edit_agent_settings",
            data_schema=_agent_profile_schema(profile, await self._model_options()),
        )

    async def async_step_remove_agent(self, user_input=None):
        profiles = self._agent_profiles()
        if len(profiles) <= 1:
            return self.async_show_menu(step_id="agents", menu_options=["add_agent", "init"])
        if user_input is not None:
            self._removing_agent_id = user_input.get("agent_id")
            return await self.async_step_remove_agent_confirm()
        return self.async_show_form(
            step_id="remove_agent",
            data_schema=_agent_choice_schema(profiles),
        )

    async def async_step_remove_agent_confirm(self, user_input=None):
        profiles = self._agent_profiles()
        profile = next(
            (item for item in profiles if item["id"] == self._removing_agent_id),
            None,
        )
        if profile is None:
            return self.async_show_menu(
                step_id="agents",
                menu_options=["add_agent", "edit_agent", "remove_agent", "init"],
            )
        if user_input is not None:
            if user_input.get("confirm_remove"):
                if len(profiles) <= 1:
                    return self.async_show_form(
                        step_id="remove_agent_confirm",
                        data_schema=_remove_confirmation_schema(),
                        errors={"base": "last_agent"},
                    )
                self._agents = [item for item in profiles if item["id"] != profile["id"]]
                return self._save_agents()
            return self.async_show_menu(
                step_id="agents",
                menu_options=["add_agent", "edit_agent", "remove_agent", "init"],
            )
        return self.async_show_form(
            step_id="remove_agent_confirm",
            data_schema=_remove_confirmation_schema(),
            description_placeholders={"agent_name": profile["name"]},
        )

    def _agent_profiles(self) -> list[dict[str, Any]]:
        if self._agents is None:
            self._agents = [profile.as_dict() for profile in get_agent_profiles(self.config_entry)]
        return self._agents

    async def _model_options(self) -> list[str]:
        if self._catalog is None:
            self._catalog = await async_entry_model_catalog(
                self.hass, self.config_entry, force=True
            )
        return list(self._catalog.models)

    def _save_agents(self):
        return self.async_create_entry(
            title="",
            data={**self.config_entry.options, CONF_AGENTS: self._agent_profiles()},
        )


def _settings_schema(
    defaults: dict[str, Any],
    *,
    model_options: list[str],
) -> vol.Schema:
    model_options = list(dict.fromkeys(model_options))
    saved_model = defaults.get(CONF_MODEL)
    model_default = saved_model or next(iter(model_options), None)
    image_model_default = defaults.get(CONF_IMAGE_MODEL, DEFAULT_IMAGE_MODEL)
    if image_model_default not in IMAGE_MODEL_QUALITY:
        image_model_default = DEFAULT_IMAGE_MODEL
    image_size_default = defaults.get(CONF_IMAGE_SIZE, DEFAULT_IMAGE_SIZE)
    if image_size_default not in IMAGE_SIZE_OPTIONS:
        image_size_default = DEFAULT_IMAGE_SIZE

    return vol.Schema(
        {
            vol.Required(SECTION_CHAT_SETTINGS): section(
                vol.Schema(
                    {
                        **(
                            {
                                vol.Optional(CONF_MODEL, default=model_default): _model_selector(
                                    model_options, saved_model=saved_model
                                )
                            }
                            if model_default is not None
                            else {}
                        ),
                        vol.Optional(
                            CONF_TEXT_VERBOSITY,
                            default=defaults.get(CONF_TEXT_VERBOSITY, DEFAULT_TEXT_VERBOSITY),
                        ): _low_medium_high_selector(),
                        vol.Optional(
                            CONF_WEB_SEARCH,
                            default=defaults.get(CONF_WEB_SEARCH, DEFAULT_WEB_SEARCH),
                        ): bool,
                    }
                ),
                {"collapsed": False},
            ),
            vol.Required(SECTION_ADVANCED_SETTINGS): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_PROMPT,
                            default=defaults.get(CONF_PROMPT, DEFAULT_PROMPT),
                        ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                        vol.Optional(
                            CONF_REASONING_EFFORT,
                            default=defaults.get(CONF_REASONING_EFFORT, DEFAULT_REASONING_EFFORT),
                        ): _low_medium_high_selector(),
                    }
                ),
                {"collapsed": True},
            ),
            vol.Required(SECTION_IMAGE_SETTINGS): section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_IMAGE_MODEL,
                            default=image_model_default,
                        ): _image_model_selector(),
                        vol.Optional(
                            CONF_IMAGE_SIZE,
                            default=image_size_default,
                        ): _image_size_selector(),
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


def _model_schema(defaults: dict[str, Any], *, model_options: list[str]) -> vol.Schema:
    model_options = list(dict.fromkeys(model_options))
    saved_model = defaults.get(CONF_MODEL)
    model_default = (
        saved_model
        if saved_model in model_options
        else next(iter(model_options), None)
    )
    if not model_options:
        return vol.Schema({})
    return vol.Schema(
        {vol.Optional(CONF_MODEL, default=model_default): _model_selector(model_options)}
    )


def _flatten_settings_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    for section_name in (
        SECTION_CHAT_SETTINGS,
        SECTION_ADVANCED_SETTINGS,
        SECTION_IMAGE_SETTINGS,
    ):
        section_data = user_input.get(section_name)
        if isinstance(section_data, Mapping):
            settings.update(section_data)
    return settings


def _new_profile_defaults(entry) -> AgentProfile:
    profiles = get_agent_profiles(entry)
    base = profiles[0]
    return AgentProfile(
        agent_id="",
        name="New assistant",
        prompt=base.prompt,
        model=base.model,
        reasoning_effort=base.reasoning_effort,
        reasoning_summary=base.reasoning_summary,
        text_verbosity=base.text_verbosity,
        web_search=base.web_search,
    )


def _profile_from_dict(data: Mapping[str, Any]) -> AgentProfile:
    return AgentProfile(
        agent_id=str(data.get("id", "")),
        name=str(data.get("name", "")),
        prompt=str(data.get("prompt", DEFAULT_PROMPT)),
        model=data.get("model") if isinstance(data.get("model"), str) else None,
        reasoning_effort=str(data.get("reasoning_effort", DEFAULT_REASONING_EFFORT)),
        reasoning_summary=str(data.get("reasoning_summary", DEFAULT_REASONING_SUMMARY)),
        text_verbosity=str(data.get("text_verbosity", DEFAULT_TEXT_VERBOSITY)),
        web_search=bool(data.get("web_search", DEFAULT_WEB_SEARCH)),
    )


def _profile_from_input(agent_id: str, user_input: Mapping[str, Any]) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id,
        name=user_input["name"].strip(),
        prompt=user_input["prompt"],
        model=user_input.get("model"),
        reasoning_effort=user_input.get("reasoning_effort", DEFAULT_REASONING_EFFORT),
        reasoning_summary=user_input.get("reasoning_summary", DEFAULT_REASONING_SUMMARY),
        text_verbosity=user_input.get("text_verbosity", DEFAULT_TEXT_VERBOSITY),
        web_search=bool(user_input.get("web_search", DEFAULT_WEB_SEARCH)),
    )


def _validate_agent_input(
    user_input: Mapping[str, Any],
    other_profiles: list[dict[str, Any]],
    *,
    allowed_models: list[str] | None = None,
    saved_model: str | None = None,
) -> str | None:
    name = user_input.get("name")
    prompt = user_input.get("prompt")
    if not isinstance(name, str) or not name.strip():
        return "invalid_agent_name"
    if len(name.strip()) > 48:
        return "agent_name_too_long"
    if not isinstance(prompt, str) or not prompt.strip():
        return "invalid_agent_prompt"
    model = user_input.get("model")
    if (
        model is not None
        and allowed_models is not None
        and model not in allowed_models
        and model != saved_model
    ):
        return "invalid_model"
    if any(
        name.strip().casefold() == str(item.get("name", "")).strip().casefold()
        for item in other_profiles
    ):
        return "duplicate_agent_name"
    return None


def _agent_profile_schema(
    profile: AgentProfile,
    model_options: list[str],
) -> vol.Schema:
    model_options = list(dict.fromkeys(model_options))
    if profile.model and profile.model not in model_options:
        model_options.append(profile.model)
    fields: dict[Any, Any] = {
        vol.Required("name", default=profile.name): selector.TextSelector(),
        vol.Required("prompt", default=profile.prompt): selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        ),
        vol.Required(
            "reasoning_effort", default=profile.reasoning_effort
        ): _low_medium_high_selector(),
        vol.Required(
            "reasoning_summary", default=profile.reasoning_summary
        ): _reasoning_summary_selector(profile.reasoning_summary),
        vol.Required(
            "text_verbosity", default=profile.text_verbosity
        ): _low_medium_high_selector(),
        vol.Required("web_search", default=profile.web_search): bool,
    }
    if model_options:
        fields[vol.Optional("model", default=profile.model or model_options[0])] = (
            _model_selector(model_options, saved_model=profile.model)
        )
    return vol.Schema(fields)


def _agent_choice_schema(profiles: list[dict[str, Any]]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("agent_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=item["id"], label=item["name"])
                        for item in profiles
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }
    )


def _remove_confirmation_schema() -> vol.Schema:
    return vol.Schema({vol.Required("confirm_remove", default=False): bool})


def _low_medium_high_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=["low", "medium", "high"],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _reasoning_summary_selector(saved_value: str = "auto") -> selector.SelectSelector:
    options = ["auto", "low", "medium", "high"]
    if saved_value not in options:
        options.append(saved_value)
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _model_selector(
    model_options: list[str], *, saved_model: str | None = None
) -> selector.SelectSelector:
    options = [selector.SelectOptionDict(value=model, label=model) for model in model_options]
    if saved_model and saved_model not in model_options:
        options.append(
            selector.SelectOptionDict(
                value=saved_model, label=f"{saved_model} (saved; not currently listed)"
            )
        )
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _image_model_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value="gpt-image-2-low", label="Low"),
                selector.SelectOptionDict(value="gpt-image-2-medium", label="Medium"),
                selector.SelectOptionDict(value="gpt-image-2-high", label="High"),
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _image_size_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value="1024x1024", label="Square (1024×1024)"),
                selector.SelectOptionDict(value="1536x1024", label="Landscape (1536×1024)"),
                selector.SelectOptionDict(value="1024x1536", label="Portrait (1024×1536)"),
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _catalog_description(catalog: ModelCatalog, saved_model: str | None = None) -> str:
    if catalog.source == "fallback":
        status = "Discovery is unavailable. Suggested models are unverified for this account."
    elif not catalog.models:
        status = "The account's model list contains no visible models."
    elif catalog.source == "cached":
        status = "Showing the last model list retrieved for this account during this session."
    else:
        status = "Models retrieved from your ChatGPT/Codex account."
    if catalog.error == "authentication":
        status += " Account discovery requires a fresh sign-in."
    elif catalog.error and catalog.source == "cached":
        status += " Refresh failed; the cached list may be outdated."
    if saved_model and saved_model not in catalog.models:
        status += (
            " Your saved model is not in this list; it is kept until you choose a replacement."
        )
    return status
