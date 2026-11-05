"""Account-bound coordinator controls, never an audio/device impersonation API."""

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers import config_validation as cv

from . import DOMAIN
from .lifecycle import loaded_runtime

schema = getattr(cv, "probatio", vol)


def register(hass):
    from .launcher import launch_info

    websocket_api.async_register_command(hass, manage)
    websocket_api.async_register_command(hass, launch_info)


@websocket_api.websocket_command(
    {
        schema.Required("type"): DOMAIN + "/voice_learning/manage",
        schema.Required("entry_id"): str,
        schema.Required("action"): schema.In(["start", "status", "cancel"]),
        schema.Optional("voice_id"): str,
        schema.Optional("satellite_id"): str,
        schema.Optional("consent"): bool,
    }
)
@websocket_api.async_response
async def manage(hass, connection, msg):
    user = await hass.auth.async_get_user(connection.user.id)
    if user is None or not user.is_active or user.system_generated:
        raise Unauthorized
    runtime = loaded_runtime(hass, msg["entry_id"])
    if runtime is None:
        connection.send_error(msg["id"], "not_ready", "Learning companion unavailable")
        return
    coordinator = runtime.coordinator
    if (
        msg["action"] != "start"
        and coordinator.actor_id not in (None, user.id)
        and not user.is_admin
    ):
        raise Unauthorized
    try:
        if msg["action"] == "start":
            # No real device adapters ship yet. A browser-supplied entity ID must
            # match an adapter registered by trusted integration code, not merely
            # an existing device/entity name.
            speaker = runtime.speakers.get(msg.get("satellite_id"))
            if not msg.get("voice_id"):
                raise ValueError
            await coordinator.start(user.id, msg["voice_id"], speaker, consent=msg.get("consent"))
        elif msg["action"] == "cancel":
            await coordinator.cancel()
    except ValueError:
        connection.send_error(
            msg["id"],
            "not_ready",
            "Fresh consent and a trusted learning adapter are required; "
            "another session may be active",
        )
        return
    connection.send_result(msg["id"], coordinator.view())
