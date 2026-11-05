"""Bounded technical setup checks; never consent, recording, or speaker identity."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from .. import DOMAIN
from .const import CONF_CONTROL_STT, CONF_PHONE_ENABLED, MODULE_URL, PANEL_PATH


def panel_status(hass):
    from homeassistant.components import frontend

    panel = hass.data.get(frontend.DATA_PANELS, {}).get(PANEL_PATH)
    if panel is None:
        return "missing"
    custom = (panel.config or {}).get("_panel_custom", {})
    ours = (
        custom.get("module_url") == MODULE_URL
        and custom.get("name") == "voice-match-launch-panel"
        and custom.get("embed_iframe") is False
        and panel.require_admin is False
    )
    return "ready" if ours else "conflict"


def technical_report(hass, entry):
    report = dict.fromkeys(("bridge", "source", "entities", "pipeline", "launcher"), "not_checked")
    if entry.state is ConfigEntryState.FAILED_UNLOAD:
        report["entities"] = "not_loaded"
        return report
    if not entry.options.get(CONF_PHONE_ENABLED, False):
        report.update(
            source="disabled", entities="disabled", pipeline="not_required", launcher="not_required"
        )
        return report

    from .stt import control_source

    try:
        source = control_source(hass, entry.options.get(CONF_CONTROL_STT))
        state = hass.states.get(source.entity_id)
        report["source"] = "available" if state and state.state != "unavailable" else "unavailable"
    except ValueError:
        report["source"] = "unavailable"

    registry = er.async_get(hass)
    ids = [
        registry.async_get_entity_id(domain, DOMAIN, entry.entry_id + suffix)
        for domain, suffix in (
            ("stt", "_phone_learning_stt"),
            ("conversation", "_phone_learning_agent"),
        )
    ]
    report["entities"] = "ready"
    for entity_id in ids:
        registered = registry.async_get(entity_id) if entity_id else None
        state = hass.states.get(entity_id) if entity_id else None
        if (
            registered is None
            or registered.config_entry_id != entry.entry_id
            or registered.disabled
            or state is None
            or state.state == "unavailable"
        ):
            report["entities"] = "unavailable"
    if entry.state is not ConfigEntryState.LOADED:
        report["entities"] = "not_loaded"

    report["pipeline"] = "missing"
    if "assist_pipeline" in hass.config.components and all(ids):
        from homeassistant.components import assist_pipeline

        pipelines = assist_pipeline.async_get_pipelines(hass)
        matches = [
            p for p in pipelines if p.stt_engine == ids[0] and p.conversation_engine == ids[1]
        ]
        if len(matches) == 1:
            report["pipeline"] = "ready"
        elif len(matches) > 1:
            report["pipeline"] = "ambiguous"
        elif any(p.stt_engine == ids[0] or p.conversation_engine == ids[1] for p in pipelines):
            report["pipeline"] = "mismatch"
    report["launcher"] = panel_status(hass)
    return report


async def async_check_setup(hass, entry, *, publish=True):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .bridge_client import BridgeClient
    from .learning_bridge_protocol import BridgeError

    data, options = entry.data, entry.options
    bridge = "unavailable"
    try:
        client = BridgeClient(data["url"], data["key"], async_get_clientsession(hass))
        if await client.call("hello", None, {}) == {"ready": True}:
            bridge = "verified"
    except BridgeError, ValueError, TypeError, KeyError:
        pass
    # An old check must not clear issues for a changed key, source or removed entry.
    if (
        hass.config_entries.async_get_entry(entry.entry_id) is not entry
        or entry.data is not data
        or entry.options is not options
    ):
        return dict.fromkeys(
            ("bridge", "source", "entities", "pipeline", "launcher"), "not_checked"
        )
    report = technical_report(hass, entry)
    report["bridge"] = bridge
    if publish:
        from .health_issues import apply_report

        apply_report(hass, entry, report)
    return report
