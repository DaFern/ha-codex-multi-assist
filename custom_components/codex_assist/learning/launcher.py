"""Read-only native launch discovery; never recording consent or session grants."""

import asyncio
import logging
import re
from pathlib import Path

import voluptuous as vol
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from . import DOMAIN
from .const import MODULE_URL, PANEL_PATH
from .learning_bridge_protocol import BridgeError
from .lifecycle import loaded_runtime

_LOGGER = logging.getLogger(__name__)
schema = getattr(cv, "probatio", vol)


async def register_panel(hass):
    if frontend.async_panel_exists(hass, PANEL_PATH):
        from .readiness import panel_status

        if panel_status(hass) == "ready":
            return
        # Never replace a panel belonging to the user or another integration.
        _LOGGER.warning(
            "Voice learning launcher path is already registered; use the manual learning steps"
        )
        return
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                MODULE_URL, str(Path(__file__).parent / "frontend" / "launch-panel.js"), False
            ),
        ]
    )
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name="voice-match-launch-panel",
        module_url=MODULE_URL,
        embed_iframe=False,
        require_admin=False,
    )


def phone_runtime(hass):
    candidates = [
        runtime.phone
        for entry in hass.config_entries.async_entries(DOMAIN)
        if (runtime := loaded_runtime(hass, entry.entry_id)) is not None
        and runtime.phone is not None
    ]
    if len(candidates) != 1 or candidates[0].controller.closing:
        raise ValueError("One enabled phone companion is required")
    return candidates[0]


def learning_pipeline(hass, phone):
    if "assist_pipeline" not in hass.config.components:
        raise ValueError("Assist is unavailable")
    from homeassistant.components import assist_pipeline

    registry = er.async_get(hass)
    stt_id = registry.async_get_entity_id(
        "stt", DOMAIN, phone.entry.entry_id + "_phone_learning_stt"
    )
    agent_id = registry.async_get_entity_id(
        "conversation", DOMAIN, phone.entry.entry_id + "_phone_learning_agent"
    )
    for entity_id in (stt_id, agent_id):
        entry = registry.async_get(entity_id) if entity_id else None
        state = hass.states.get(entity_id) if entity_id else None
        if (
            entry is None
            or entry.config_entry_id != phone.entry.entry_id
            or entry.disabled
            or state is None
            or state.state == "unavailable"
        ):
            raise ValueError("Learning entities unavailable")
    matches = [
        pipeline
        for pipeline in assist_pipeline.async_get_pipelines(hass)
        if pipeline.stt_engine == stt_id and pipeline.conversation_engine == agent_id
    ]
    if len(matches) != 1:
        raise ValueError("One matching learning assistant is required")
    return matches[0].id


@websocket_api.websocket_command({schema.Required("type"): DOMAIN + "/voice_learning/launch_info"})
@websocket_api.async_response
async def launch_info(hass, connection, msg):
    try:
        async with asyncio.timeout(15):
            phone = phone_runtime(hass)
            login_id = phone.authorize(connection, connection.user.id)
            own = await phone.controller.bridge.call("own_profile", connection.user.id, {})
            if (
                not isinstance(own, dict)
                or not isinstance(own.get("id"), str)
                or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", own["id"]) is None
            ):
                connection.send_error(
                    msg["id"],
                    "own_profile_required",
                    "Create or check your own voice profile in Voice Match first",
                )
                return
            if (
                phone_runtime(hass) is not phone
                or phone.authorize(connection, connection.user.id) != login_id
            ):
                raise ValueError("Phone login or companion changed")
            pipeline_id = learning_pipeline(hass, phone)
    except BridgeError, ValueError, TimeoutError:
        connection.send_error(
            msg["id"],
            "not_ready",
            "Voice learning launch is unavailable. "
            "Check the companion and learning assistant setup",
        )
        return
    # IDs identify only this authenticated account and current pipeline. These are
    # not capabilities: native STT rechecks its own login and separate consent.
    connection.send_result(
        msg["id"],
        {
            "user_id": connection.user.id,
            "profile_id": own["id"],
            "pipeline_id": pipeline_id,
        },
    )
