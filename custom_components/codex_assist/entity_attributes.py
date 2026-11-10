"""Bounded, explicitly curated attribute projection; no HA or service access."""

from __future__ import annotations

import math
from typing import Any

# Attribute names alone are not a permission boundary. The caller must first
# enforce current exposure and read permissions. Domain scoping prevents an
# arbitrary custom attribute with a familiar name from being dumped by default.
COMMON_ATTRIBUTES = frozenset({"device_class", "unit_of_measurement"})
DOMAIN_ATTRIBUTES = {
    "weather": frozenset({
        "temperature", "apparent_temperature", "dew_point", "temperature_unit",
        "humidity", "pressure", "pressure_unit", "wind_speed", "wind_gust_speed",
        "wind_bearing", "wind_speed_unit", "visibility", "visibility_unit",
        "ozone", "cloud_coverage", "uv_index", "precipitation_unit",
    }),
    "climate": frozenset({
        "temperature", "current_temperature", "target_temp_high", "target_temp_low",
        "min_temp", "max_temp", "target_temp_step", "humidity", "current_humidity",
        "hvac_action", "hvac_modes", "preset_mode", "preset_modes", "fan_mode",
        "fan_modes", "swing_mode", "swing_modes", "swing_horizontal_mode",
        "swing_horizontal_modes",
    }),
    "water_heater": frozenset({
        "temperature", "current_temperature", "min_temp", "max_temp",
        "operation_mode", "operation_list", "away_mode",
    }),
    "humidifier": frozenset({
        "humidity", "current_humidity", "min_humidity", "max_humidity",
        "mode", "available_modes",
    }),
    "light": frozenset({
        "brightness", "color_mode", "supported_color_modes", "color_temp_kelvin",
        "min_color_temp_kelvin", "max_color_temp_kelvin", "rgb_color", "hs_color",
        "effect", "effect_list",
    }),
    "fan": frozenset({
        "percentage", "percentage_step", "preset_mode", "preset_modes",
        "oscillating", "direction",
    }),
    "cover": frozenset({"current_position", "current_tilt_position"}),
    "media_player": frozenset({
        "volume_level", "is_volume_muted", "media_title", "media_artist",
        "media_album_name", "media_duration", "media_position", "media_content_type",
        "source", "source_list", "sound_mode", "sound_mode_list", "shuffle", "repeat",
    }),
    "vacuum": frozenset({"battery_level", "fan_speed", "fan_speed_list"}),
    "lock": frozenset({"battery_level"}),
    "sensor": frozenset({"state_class", "battery_level"}),
    "switch": frozenset({"current_power_w", "current_power_a", "battery_level"}),
}
ATTRIBUTE_NAMES = sorted(COMMON_ATTRIBUTES.union(*DOMAIN_ATTRIBUTES.values()))
MAX_ATTRIBUTES = 8
MAX_TEXT = 256
MAX_LIST = 16


def _safe_value(value: Any) -> bool:
    """Never stringify objects, nested mappings, huge lists or nonfinite values."""
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return abs(value) < 1e20 and math.isfinite(value)
    return isinstance(value, str) and len(value) <= MAX_TEXT


def _bounded_value(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return len(value) <= MAX_LIST and all(_safe_value(item) for item in value)
    return _safe_value(value)


def project_attributes(
    domain: str, attributes: dict[str, Any], requested: list[str], *, temperature_unit: str,
) -> dict[str, Any]:
    """Project only requested safe fields, with honest absence/withholding markers."""
    if not requested or len(requested) > MAX_ATTRIBUTES:
        raise ValueError("Invalid attribute count")
    allowed = COMMON_ATTRIBUTES | DOMAIN_ATTRIBUTES.get(domain, frozenset())
    values = {}
    missing = []
    withheld = []
    for name in dict.fromkeys(requested):
        if name not in allowed:
            withheld.append(name)
            continue
        if name not in attributes or attributes[name] is None:
            missing.append(name)
            continue
        value = attributes[name]
        if not _bounded_value(value):
            withheld.append(name)
            continue
        item = {"value": list(value) if isinstance(value, (list, tuple)) else value}
        unit = None
        if domain == "weather":
            unit_key = {
                "temperature": "temperature_unit", "apparent_temperature": "temperature_unit",
                "dew_point": "temperature_unit", "pressure": "pressure_unit",
                "wind_speed": "wind_speed_unit", "wind_gust_speed": "wind_speed_unit",
                "visibility": "visibility_unit",
            }.get(name)
            if unit_key:
                unit = attributes.get(unit_key)
            elif name == "wind_bearing" and isinstance(value, (int, float)):
                unit = "°"
        elif domain in {"climate", "water_heater"} and name in {
            "temperature", "current_temperature", "target_temp_high", "target_temp_low",
            "min_temp", "max_temp", "target_temp_step",
        }:
            unit = temperature_unit
        if name in {
            "humidity", "current_humidity", "min_humidity", "max_humidity", "battery_level",
            "percentage", "percentage_step", "current_position", "current_tilt_position",
            "cloud_coverage",
        }:
            unit = "%"
        if domain == "media_player" and name in {"media_duration", "media_position"}:
            unit = "s"
        if domain == "light" and name.endswith("kelvin"):
            unit = "K"
        if unit is not None and isinstance(unit, str) and len(unit) <= 32:
            item["unit"] = unit
        values[name] = item
    return {"attributes": values, "missing": missing, "withheld": withheld}
