"""Typed ordinary controls with exact targets; no model-selected service bridge."""

import asyncio

import probatio
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm

from .guest_policy import async_capability_check, async_guest_snapshot, async_speaker_snapshot
from .protected_interpretation import resolve_reference

ACTIONS = (
    "state", "turn_on", "turn_off", "set_light", "set_fan_speed", "set_temperature",
    "set_hvac_mode", "set_preset", "open_blind", "close_blind", "stop_blind",
    "set_blind_position", "stop", "pause", "resume", "next", "previous", "volume",
    "volume_up", "volume_down", "mute", "unmute", "seek", "shuffle", "repeat",
    "power_on", "power_off", "source",
)
DOMAINS = {"light", "switch", "fan", "climate", "cover", "media_player"}
SIMPLE = {
    "turn_on": "turn_on", "turn_off": "turn_off", "stop": "media_stop",
    "pause": "media_pause", "resume": "media_play", "next": "media_next_track",
    "previous": "media_previous_track", "volume_up": "volume_up", "volume_down": "volume_down",
    "power_on": "turn_on", "power_off": "turn_off", "open_blind": "open_cover",
    "close_blind": "close_cover", "stop_blind": "stop_cover",
}


def _plan(action, args):
    if action in SIMPLE:
        return SIMPLE[action], {}
    if action == "set_light":
        return "turn_on", {
            key: args[source] for source, key in (
                ("level", "brightness_pct"), ("rgb", "rgb_color"), ("kelvin", "color_temp_kelvin"),
            ) if source in args
        }
    if action in {"mute", "unmute"}:
        return "volume_mute", {"is_volume_muted": action == "mute"}
    mapping = {
        "set_fan_speed": ("set_percentage", "percentage", "level"),
        "set_temperature": ("set_temperature", "temperature", "temperature"),
        "set_hvac_mode": ("set_hvac_mode", "hvac_mode", "mode"),
        "set_preset": ("set_preset_mode", "preset_mode", "mode"),
        "set_blind_position": ("set_cover_position", "position", "level"),
        "volume": ("volume_set", "volume_level", "level"),
        "seek": ("media_seek", "seek_position", "position"),
        "shuffle": ("shuffle_set", "shuffle", "enabled"),
        "repeat": ("repeat_set", "repeat", "mode"),
        "source": ("select_source", "source", "mode"),
    }
    service, key, source = mapping[action]
    value = args[source]
    return service, {key: value / 100 if action == "volume" else value}


class ProtectedDeviceTool(llm.Tool):
    """Expose finite supported ordinary actions; policy independently gates each target."""

    name = "codex_assist__ordinary_devices"
    title = "Ordinary devices"
    integration = "codex_assist"
    description = (
        "Read permitted live device state or control lights, fans, thermostats, blinds "
        "and media/TV players. No locks, alarms, doors, garage doors, scripts or arbitrary "
        "services. Use state first when capability options or numeric limits are needed. "
        "level is percent; temperature uses the device unit; rgb is three 0-255 values; "
        "kelvin is colour temperature; position is playback seconds; mode is an exact "
        "permitted HVAC/preset/source/repeat option. Prefer this for non-Music-Assistant media."
    )
    annotations = llm.ToolAnnotations(
        read_only=False, destructive=True, idempotent=False, open_world=False,
    )
    parameters = probatio.Schema({
        probatio.Required("action"): probatio.In(ACTIONS),
        probatio.Required("entity_ids"): probatio.All([str], probatio.Length(min=1, max=32)),
        probatio.Optional("level"): probatio.All(
            probatio.Coerce(float), probatio.Range(min=0, max=100),
        ),
        probatio.Optional("temperature"): probatio.All(
            probatio.Coerce(float), probatio.Range(min=-100, max=1000),
        ),
        probatio.Optional("position"): probatio.All(
            probatio.Coerce(float), probatio.Range(min=0, max=86400),
        ),
        probatio.Optional("rgb"): probatio.All([int], probatio.Length(min=3, max=3)),
        probatio.Optional("kelvin"): probatio.All(int, probatio.Range(min=1000, max=20000)),
        probatio.Optional("mode"): probatio.All(str, probatio.Length(min=1, max=128)),
        probatio.Optional("enabled"): bool,
    })

    def __init__(self, authorization, catalogue):
        self._auth = authorization
        self.reference_catalogue = catalogue
        self.validate_references = None
        self.remaining_actions = 32

    async def async_call(self, hass, tool_input, llm_context):
        auth = self._auth
        completed = 0
        if (not auth.valid() or llm_context.context is not auth.context
                or llm_context.assistant != "conversation"):
            return llm.ToolResult(data={"error": "This control is not authorised."}, error=True)
        try:
            args = self.parameters(tool_input.tool_args)
            action = args["action"]
            groups = {row["entity_id"]: row["members"] for row in self.reference_catalogue
                      if "members" in row}
            ids = []
            for value in args["entity_ids"]:
                eid = resolve_reference(
                    value, self.reference_catalogue, DOMAINS | {"group"},
                ) or value
                ids.extend(groups.get(eid, [eid]))
            ids = tuple(dict.fromkeys(ids))
            if not 0 < len(ids) <= (32 if action == "state" else self.remaining_actions):
                raise PermissionError
            if self.validate_references and not await self.validate_references():
                raise PermissionError
            if action == "state":
                snapshot, subject = (
                    (async_speaker_snapshot, auth.user_id) if hasattr(auth, "user_id")
                    else (async_guest_snapshot, auth.role_id)
                )
                rows = await snapshot(hass, subject, ids)
                if (rows is None or not auth.valid()
                        or {row["entity_id"] for row in rows} != set(ids)):
                    raise PermissionError
                return llm.ToolResult(data={"response_type": "query_answer", "entities": rows})
            service, data = _plan(action, args)
            registry = er.async_get(hass)
            identities = {eid: registry.async_get(eid) for eid in ids}
            if not await async_capability_check(hass, auth, ids, action=action, args=args):
                raise PermissionError
            for eid in ids:
                if not await async_capability_check(hass, auth, (eid,), action=action, args=args):
                    raise PermissionError
                if not auth.valid() or registry.async_get(eid) is not identities[eid]:
                    raise PermissionError
                claim = getattr(self, "claim_effect", None)
                if claim is not None and not claim(
                    eid.partition(".")[0], service, {"entity_id": eid, **data},
                ):
                    raise PermissionError
                await hass.services.async_call(
                    eid.partition(".")[0], service, {"entity_id": eid, **data},
                    blocking=True, context=auth.context,
                )
                completed += 1
            return llm.ToolResult(data={
                "status": "accepted", "completed": completed, "operation": action,
                "entity_ids": list(ids),
            })
        except asyncio.CancelledError:
            raise
        except Exception:
            return llm.ToolResult(data={
                "error": "The requested control is unavailable, unsupported or not permitted.",
                "completed": completed,
            }, error=True)
