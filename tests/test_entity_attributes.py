"""Safe attribute projection without HA, household names or provider access."""

import pytest

from custom_components.codex_assist.entity_attributes import project_attributes


def project(domain, attributes, requested):
    return project_attributes(domain, attributes, requested, temperature_unit="°C")


@pytest.mark.parametrize("domain,attribute,value,unit", [
    ("weather", "wind_speed", 4.44, "mph"),
    ("weather", "wind_bearing", 111.2, "°"),
    ("weather", "pressure", 1016.2, "hPa"),
    ("climate", "temperature", 21, "°C"),
    ("water_heater", "current_temperature", 55, "°C"),
    ("humidifier", "current_humidity", 45, "%"),
    ("fan", "percentage", 30, "%"),
    ("cover", "current_position", 40, "%"),
    ("light", "color_temp_kelvin", 3000, "K"),
    ("media_player", "media_duration", 120, "s"),
    ("vacuum", "battery_level", 75, "%"),
    ("lock", "battery_level", 80, "%"),
])
def test_cross_domain_values_and_units(domain, attribute, value, unit):
    data = project(domain, {
        attribute: value, "wind_speed_unit": "mph", "pressure_unit": "hPa",
    }, [attribute])
    assert data == {"attributes": {attribute: {"value": value, "unit": unit}},
                    "missing": [], "withheld": []}


def test_no_dump_unknown_keys_or_cross_domain_attributes():
    data = project("weather", {
        "wind_speed": 4, "temperature": 8, "api_key": "synthetic-private",
        "media_title": "not a weather attribute",
    }, ["wind_speed", "media_title", "api_key"])
    assert data["attributes"] == {"wind_speed": {"value": 4}}
    assert data["withheld"] == ["media_title", "api_key"]
    assert "synthetic-private" not in str(data)
    assert "temperature" not in str(data)


def test_missing_null_and_zero_are_distinct_and_no_units_are_guessed():
    data = project("weather", {"wind_speed": 0, "pressure": None}, [
        "wind_speed", "pressure", "wind_gust_speed",
    ])
    assert data["attributes"] == {"wind_speed": {"value": 0}}
    assert data["missing"] == ["pressure", "wind_gust_speed"]


@pytest.mark.parametrize("value", [
    float("nan"), float("inf"), 10**1000, {"nested": "synthetic-private"},
    "x" * 257, ["x"] * 17, [[1]], object(),
])
def test_unbounded_or_complex_values_are_withheld(value):
    data = project("media_player", {"media_title": value}, ["media_title"])
    assert data == {"attributes": {}, "missing": [], "withheld": ["media_title"]}


def test_safe_lists_are_copied_and_duplicate_requests_coalesce():
    values = ["heat", "off"]
    data = project("climate", {"hvac_modes": values}, ["hvac_modes", "hvac_modes"])
    assert data["attributes"] == {"hvac_modes": {"value": values}}
    assert data["attributes"]["hvac_modes"]["value"] is not values


@pytest.mark.parametrize("requested", [[], ["humidity"] * 9])
def test_request_count_is_bounded(requested):
    with pytest.raises(ValueError):
        project("weather", {}, requested)
