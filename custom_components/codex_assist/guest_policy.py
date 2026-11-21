"""Guest role selection and fail-closed policy client; no ingress or tool grants."""

import asyncio
import math
from importlib import import_module

CONF_GUEST_ROLE = "guest_voice_role_id"
GUEST_DOMAINS = frozenset({"switch", "light", "fan", "media_player"})
ORDINARY_DOMAINS = GUEST_DOMAINS | {"climate", "cover"}
RICH_ATTRIBUTES = {
    "brightness", "color_mode", "supported_color_modes", "rgb_color", "color_temp_kelvin",
    "min_color_temp_kelvin", "max_color_temp_kelvin", "percentage", "oscillating", "direction",
    "temperature", "current_temperature", "min_temp", "max_temp", "temperature_unit",
    "hvac_modes", "preset_modes", "preset_mode", "device_class", "current_position",
    "volume_level", "is_volume_muted", "media_position", "media_duration", "media_title",
    "media_artist", "shuffle", "repeat", "source", "source_list",
    "supported_actions",
    "readable_fields",
}


def capabilities_supported():
    try:
        value = getattr(_provider(), "VOICE_CAPABILITY_VERSION", None)
        return type(value) is int and value == 1
    except Exception:
        return False


async def async_capability_check(hass, auth, ids, *, action="read", args=None):
    """Use only the additive finite-capability policy API, never an old permissive fallback."""
    try:
        provider = _provider()
        if type(getattr(provider, "VOICE_CAPABILITY_VERSION", None)) is not int:
            return False
        if provider.VOICE_CAPABILITY_VERSION != 1:
            return False
        subject = (
            {"user_id": auth.user_id} if hasattr(auth, "user_id")
            else {"guest_role_id": auth.role_id}
        )
        async with asyncio.timeout(2):
            result = await provider.async_check_voice_capability(
                hass, ids, action=action, args=args, **subject,
            )
        return auth.valid() and getattr(result, "allowed", None) is True
    except Exception:
        return False


def _provider():
    provider = import_module("custom_components.ha_rbac.assist_policy")
    if (
        type(getattr(provider, "GUEST_POLICY_VERSION", None)) is not int
        or provider.GUEST_POLICY_VERSION != 1
    ):
        raise ValueError("Unsupported guest policy provider")
    return provider


async def async_guest_role_choices(hass):
    """Fetch bounded role labels for the admin editor, never the role rules."""
    try:
        async with asyncio.timeout(2):
            result = await _provider().async_guest_role_choices(hass)
        if (
            type(result) is not dict or set(result) != {"available", "roles"}
            or result["available"] is not True or type(result["roles"]) is not list
            or len(result["roles"]) > 100
        ):
            return None
        roles = {}
        for row in result["roles"]:
            if (
                type(row) is not dict or set(row) != {"id", "name"}
                or any(type(row[key]) is not str or not 0 < len(row[key]) <= 128
                       or not row[key].isprintable() for key in ("id", "name"))
                or row["id"] in roles
            ):
                return None
            roles[row["id"]] = row["name"]
        return roles
    except Exception:
        return None


async def async_check_guest_action(hass, role_id, entity_ids, *, operation="read"):
    """Return a boolean decision only; caller must recheck its original turn."""
    if (
        type(role_id) is not str or not 0 < len(role_id) <= 128
        or type(entity_ids) is not tuple or not 0 < len(entity_ids) <= 32
        or any(type(eid) is not str or len(eid) > 255
               or eid.partition(".")[0] not in GUEST_DOMAINS for eid in entity_ids)
        or len(set(entity_ids)) != len(entity_ids)
        or type(operation) is not str
    ):
        return False
    try:
        async with asyncio.timeout(2):
            result = await _provider().async_check_guest_action(
                hass, entity_ids, guest_role_id=role_id, operation=operation,
            )
        return getattr(result, "allowed", None) is True
    except Exception:
        return False


async def async_guest_snapshot(hass, role_id, entity_ids):
    """Validate a provider projection; never render HA templates or add attributes."""
    return await _async_snapshot(hass, entity_ids, guest_role_id=role_id)


async def async_speaker_action(hass, user_id, entity_ids, *, operation="read"):
    """A recognised speaker uses their own native/RBAC policy, never a kiosk ceiling."""
    if type(user_id) is not str or not 0 < len(user_id) <= 128:
        return False
    try:
        provider = _provider()
        if type(getattr(provider, "VOICE_POLICY_VERSION", None)) is not int:
            return False
        if provider.VOICE_POLICY_VERSION != 1:
            return False
        async with asyncio.timeout(2):
            result = await provider.async_check_voice_action(
                hass, entity_ids, user_id=user_id, operation=operation,
            )
        return getattr(result, "allowed", None) is True
    except Exception:
        return False


async def async_speaker_snapshot(hass, user_id, entity_ids):
    """Read only the recognised speaker's current role/native projection."""
    return await _async_snapshot(hass, entity_ids, user_id=user_id)


async def async_voice_references(hass, entity_ids, *, guest_role_id=None, user_id=None):
    """Fetch bounded policy-filtered aliases/rooms, without reading private registries."""
    try:
        provider = _provider()
        version = getattr(provider, "VOICE_REFERENCE_VERSION", None)
        if version is None:
            return []  # Older providers retain their exact-entity-only vocabulary.
        if type(version) is not int or version != 1:
            return None
        async with asyncio.timeout(2):
            result = await provider.async_project_voice_references(
                hass, entity_ids, guest_role_id=guest_role_id, user_id=user_id,
            )
        if (
            type(result) is not dict or set(result) != {"available", "references"}
            or result["available"] is not True or type(result["references"]) is not list
            or len(result["references"]) > 1056
        ):
            return None
        seen = set()
        for row in result["references"]:
            if (
                type(row) is not dict or not {"entity_id", "name"} <= set(row)
                or not set(row) <= {
                    "entity_id", "name", "aliases", "area", "area_aliases", "members",
                }
                or any(type(row[key]) is not str or not 0 < len(row[key]) <= 255
                       or not row[key].isprintable() for key in ("entity_id", "name"))
                or row["entity_id"] in seen
            ):
                return None
            if "area" in row and (type(row["area"]) is not str or not 0 < len(row["area"]) <= 128):
                return None
            for key in ("aliases", "area_aliases"):
                if key in row and (
                    type(row[key]) is not list or len(row[key]) > 8
                    or any(type(value) is not str or not 0 < len(value) <= 128
                           or not value.isprintable() for value in row[key])
                ):
                    return None
            members = row.get("members")
            if members is not None:
                if (type(members) is not list or not 0 < len(members) <= 32
                        or any(type(eid) is not str or eid not in entity_ids for eid in members)
                        or len(set(members)) != len(members)):
                    return None
            elif row["entity_id"] not in entity_ids:
                return None
            seen.add(row["entity_id"])
        return result["references"]
    except ImportError:
        return []
    except Exception:
        return None


async def _async_snapshot(hass, entity_ids, *, guest_role_id=None, user_id=None):
    role_id = guest_role_id if user_id is None else user_id
    if (
        type(role_id) is not str or not 0 < len(role_id) <= 128
        or type(entity_ids) is not tuple or not 0 < len(entity_ids) <= 32
        or any(type(eid) is not str or len(eid) > 255 for eid in entity_ids)
        or len(set(entity_ids)) != len(entity_ids)
    ):
        return None
    try:
        async with asyncio.timeout(2):
            provider = _provider()
            rich = getattr(provider, "VOICE_CAPABILITY_VERSION", None) == 1
            if rich:
                result = await provider.async_project_voice_capabilities(
                    hass, entity_ids, guest_role_id=guest_role_id, user_id=user_id,
                )
            elif user_id is None:
                result = await provider.async_project_guest_context(
                    hass, entity_ids, guest_role_id=role_id,
                )
            else:
                if type(getattr(provider, "VOICE_POLICY_VERSION", None)) is not int:
                    return None
                if provider.VOICE_POLICY_VERSION != 1:
                    return None
                result = await provider.async_project_voice_context(
                    hass, entity_ids, user_id=user_id,
                )
        if (
            type(result) is not dict or set(result) != {"available", "entities"}
            or result["available"] is not True or type(result["entities"]) is not list
            or len(result["entities"]) > 32
        ):
            return None
        seen = set()
        for row in result["entities"]:
            if (
                type(row) is not dict
                or not {"entity_id", "state", "attributes"} <= set(row)
                or not set(row) <= {"entity_id", "name", "state", "attributes"}
                or type(row["entity_id"]) is not str or row["entity_id"] not in entity_ids
                or row["entity_id"] in seen or type(row["attributes"]) is not dict
                or (not rich and row["attributes"] != {})
                or any(type(row[key]) is not str or not 0 < len(row[key]) <= 256
                       or not row[key].isprintable()
                       for key in ("state", "name") if key in row)
            ):
                return None
            if len(row["attributes"]) > 24 or not set(row["attributes"]) <= RICH_ATTRIBUTES:
                return None
            for value in row["attributes"].values():
                values = value if type(value) is list else [value]
                if len(values) > 64 or any(
                    type(item) not in {str, int, float, bool}
                    or (type(item) is str and (len(item) > 256 or not item.isprintable()))
                    or (type(item) is float and not math.isfinite(item))
                    for item in values
                ):
                    return None
            seen.add(row["entity_id"])
        return result["entities"]
    except Exception:
        return None
