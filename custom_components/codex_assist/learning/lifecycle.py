"""Entry-scoped learning setup, retry and fail-closed shutdown."""

from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.setup import async_setup_component

from .. import DOMAIN, async_update_listener
from ..entry_modules import EntryModule, ModuleRuntime
from .bridge_client import BridgeClient
from .const import CONF_CONTROL_STT, CONF_PHONE_ENABLED
from .coordinator import Coordinator
from .health_issues import apply_report, observe
from .learning_bridge_protocol import BridgeError
from .phone_runtime import PhoneRuntime

API_REGISTERED = DOMAIN + "_learning_api_registered"


@dataclass(frozen=True)
class LearningRuntime(ModuleRuntime):
    coordinator: Coordinator
    phone: PhoneRuntime | None
    speakers: dict[str, Any] = field(default_factory=dict)


def loaded_runtime(hass, entry_id):
    """Never expose a partial setup, failed unload, or another module's runtime."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        return None
    runtime = getattr(entry, "runtime_data", None)
    return runtime if isinstance(runtime, LearningRuntime) else None


async def async_setup_learning(hass, entry):
    data, options = entry.data, entry.options
    bridge = BridgeClient(data["url"], data["key"], async_get_clientsession(hass))
    try:
        if await bridge.call("hello", None, {}) != {"ready": True}:
            raise BridgeError("Learning bridge unavailable")
    except BridgeError:
        if (
            hass.config_entries.async_get_entry(entry.entry_id) is entry
            and entry.data is data
            and entry.options is options
        ):
            observe(hass, entry, "bridge", "unavailable")
        raise ConfigEntryNotReady("Learning bridge pairing is unavailable") from None
    if (
        hass.config_entries.async_get_entry(entry.entry_id) is not entry
        or entry.data is not data
        or entry.options is not options
    ):
        raise ConfigEntryNotReady("Learning setup changed; pairing must be checked again")
    observe(hass, entry, "bridge", "verified")

    phone = None
    if entry.options.get(CONF_PHONE_ENABLED, False):
        from .stt import control_source

        try:
            control_source(hass, entry.options.get(CONF_CONTROL_STT))
        except ValueError:
            observe(hass, entry, "source", "unavailable")
            raise ConfigEntryNotReady(
                "Phone learning needs an ordinary Wyoming Whisper STT source"
            ) from None
        phone = PhoneRuntime(hass, entry, bridge, entry.options[CONF_CONTROL_STT])
        observe(hass, entry, "source", "available")

    coordinator = Coordinator(
        bridge,
        task_factory=lambda coroutine: entry.async_create_background_task(
            hass, coroutine, "voice_match_learning"
        ),
    )
    platforms = (Platform.STT, Platform.CONVERSATION) if phone is not None else ()
    entry.runtime_data = LearningRuntime(EntryModule.VOICE_MATCH, platforms, coordinator, phone)

    if await async_setup_component(hass, "panel_custom", {}):
        from .launcher import register_panel

        await register_panel(hass)
    if not hass.data.get(API_REGISTERED):
        from .websocket_api import register

        register(hass)
        hass.data[API_REGISTERED] = True

    if platforms:
        await hass.config_entries.async_forward_entry_setups(entry, platforms)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    def check_loaded():
        if entry.state is ConfigEntryState.LOADED:
            from .readiness import technical_report

            report = technical_report(hass, entry)
            # Platform entities can still be finishing their initial add jobs.
            # Check setup can diagnose missing entities once loading has settled.
            if report["entities"] not in {"ready", "disabled"}:
                report["entities"] = report["pipeline"] = "not_checked"
            apply_report(hass, entry, report)

    entry.async_on_unload(entry.async_on_state_change(check_loaded))
    return True


async def async_unload_learning(hass, entry):
    runtime = entry.runtime_data
    await runtime.coordinator.cancel()
    if runtime.coordinator.view()["restored"] is False:
        return False
    if runtime.phone is not None and not await runtime.phone.shutdown():
        return False
    if runtime.platforms:
        return await hass.config_entries.async_unload_platforms(entry, runtime.platforms)
    return True
