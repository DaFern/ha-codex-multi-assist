"""Endpoint suggestions from HA's cached Supervisor metadata, never authority."""

import re


def origins_from_metadata(addons):
    """Return bounded internal origins only; never return options, keys or URLs."""
    origins = set()
    if not isinstance(addons, dict):
        return []
    for slug, info in list(addons.items())[:128]:
        if (
            not isinstance(slug, str)
            or not slug.endswith("_voice_match")
            or not isinstance(info, dict)
            or info.get("name") != "Wyoming Voice Match"
        ):
            continue
        hostname, port = info.get("hostname"), info.get("ingress_port")
        if (
            not isinstance(hostname, str)
            or len(hostname) > 253
            or re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", hostname) is None
            or type(port) is not int
            or not 1 <= port <= 65535
        ):
            continue
        origins.add(f"http://{hostname}:{port}")
    return sorted(origins)[:8]


def suggested_origins(hass):
    """No Supervisor on Core-only installs: retain the manual pairing route."""
    if "hassio" not in hass.config.components:
        return []
    from homeassistant.components.hassio import HassioNotReadyError, get_addons_info

    try:
        return origins_from_metadata(get_addons_info(hass))
    except HassioNotReadyError:
        return []
