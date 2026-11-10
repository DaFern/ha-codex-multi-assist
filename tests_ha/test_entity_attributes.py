"""Real native provider discovery, exposure, permissions and multi-agent delivery."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("homeassistant.components.llm",
                    reason="Native tool providers require HA 2026.8+")

from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm
from test_clarification_followups import clarification_entry as clarification_entry
from test_web_search_delivery import (
    COMPLETED,
    call_event,
    model_round,
    text_events,
)
from test_web_search_delivery import backend as backend

from custom_components.codex_assist import DOMAIN
from custom_components.codex_assist.llm import (
    TOOL_NAME,
    EntityAttributesTool,
    async_get_tools,
    schema,
)
from custom_components.codex_assist.schema_compat import to_openapi


@pytest.fixture
def entry_settings():
    profiles = [{"id": "primary", "name": "Codex Assist", "prompt": "Be concise."}]
    profiles.extend(
        {"id": f"profile_{index}", "name": f"Custom reader {index}", "prompt": "Be accurate."}
        for index in range(1, 8)
    )
    return {}, {"agents": profiles}


@pytest.fixture
def web_search():
    return False


def context(user_id=None):
    return llm.LLMContext(
        platform=DOMAIN, context=Context(user_id=user_id), language="en",
        assistant="conversation", device_id=None,
    )


def unpack(result):
    data = result.data if hasattr(result, "data") else result
    return data.get("data", data) if data.get("response_type") == "query_answer" else data


async def read(hass, ctx=None, **args):
    return unpack(await EntityAttributesTool().async_call(
        hass, llm.ToolInput(tool_name=TOOL_NAME, tool_args={
            "name": "Test weather", "attributes": ["wind_speed"], **args,
        }), ctx or context(),
    ))


def expose(hass, entity_id="weather.test", name="Test weather", **attrs):
    hass.states.async_set(entity_id, "partlycloudy", {"friendly_name": name, **attrs})
    async_expose_entity(hass, "conversation", entity_id, True)


async def test_native_discovery_schema_and_read_only_result(hass, clarification_entry):
    expose(hass, wind_speed=4.44, wind_speed_unit="mph", api_key="synthetic-private")
    api = await llm.async_get_api(hass, llm.LLM_API_ASSIST, context())
    tool = next(tool for tool in api.tools if tool.name == TOOL_NAME)
    schema = to_openapi(tool.parameters, custom_serializer=api.custom_serializer)
    assert set(schema["required"]) == {"name", "attributes"}
    assert "wind_speed" in str(schema)
    assert tool.annotations.read_only is True
    data = unpack(await api.async_call_tool(llm.ToolInput(
        tool_name=tool.name, tool_args={"name": "Test weather", "attributes": ["wind_speed"]},
    )))
    assert data == {"entity_id": "weather.test", "attributes": {
        "wind_speed": {"value": 4.44, "unit": "mph"}}, "missing": [], "withheld": []}
    assert "synthetic-private" not in str(data)
    # Reusing an already prepared API must not retain the original exposure.
    async_expose_entity(hass, "conversation", "weather.test", False)
    denied = unpack(await api.async_call_tool(llm.ToolInput(
        tool_name=tool.name, tool_args={"name": "Test weather", "attributes": ["wind_speed"]},
    )))
    assert "error" in denied
    assert "4.44" not in str(denied)


@pytest.mark.parametrize("domain,attribute,value,unit", [
    ("weather", "wind_speed", 0, "mph"),
    ("climate", "temperature", 21, "°C"),
    ("water_heater", "current_temperature", 55, "°C"),
    ("humidifier", "current_humidity", 45, "%"),
    ("light", "color_temp_kelvin", 3000, "K"),
    ("fan", "percentage", 30, "%"),
    ("cover", "current_position", 40, "%"),
    ("media_player", "media_duration", 120, "s"),
    ("vacuum", "battery_level", 75, "%"),
    ("lock", "battery_level", 80, "%"),
    ("sensor", "battery_level", 90, "%"),
])
async def test_native_api_reads_other_domains_without_service_calls(
    hass, clarification_entry, monkeypatch, domain, attribute, value, unit,
):
    expose(hass, f"{domain}.test", "Test device", **{
        attribute: value, "wind_speed_unit": "mph",
    })
    api = await llm.async_get_api(hass, llm.LLM_API_ASSIST, context())
    service = AsyncMock(side_effect=AssertionError("Attribute queries must not call services"))
    monkeypatch.setattr(type(hass.services), "async_call", service)
    data = unpack(await api.async_call_tool(llm.ToolInput(
        tool_name=TOOL_NAME, tool_args={
            "name": "Test device", "domain": [domain], "attributes": [attribute],
        },
    )))
    assert data["attributes"] == {attribute: {"value": value, "unit": unit}}
    service.assert_not_called()


async def test_every_saved_agent_including_beyond_four_can_read_weather(
    hass, clarification_entry, backend,
):
    expose(hass, wind_speed=4.44, wind_speed_unit="mph")
    planned, requests = backend
    agents = [state.entity_id for state in hass.states.async_all("conversation")
              if state.entity_id != "conversation.home_assistant"]
    assert len(agents) == 8
    for index, agent_id in enumerate(agents):
        model_round(planned, [call_event(f"weather-{index}", TOOL_NAME, {
            "name": "Test weather", "attributes": ["wind_speed"], "domain": ["weather"],
        }), COMPLETED])
        model_round(planned, text_events("The wind speed is 4.44 mph.") + [COMPLETED])
        result = await conversation.async_converse(
            hass, "What is the wind speed from Test weather?", None, Context(),
            language="en", agent_id=agent_id,
        )
        assert result.response.speech["plain"]["speech"] == "The wind speed is 4.44 mph."
        payloads = [payload for path, payload in requests if path.endswith("/responses")]
        assert len(payloads) == (index + 1) * 2
        assert any(tool["name"] == TOOL_NAME for tool in payloads[-2]["tools"])
        assert "4.44" in str(payloads[-1]["input"])
    assert not planned


async def test_newly_added_ninth_agent_gets_the_tool_without_named_registration(
    hass, clarification_entry, backend,
):
    options = dict(clarification_entry.options)
    options["agents"] = [*options["agents"], {
        "id": "added_later", "name": "Additional reader", "prompt": "Be accurate.",
    }]
    hass.config_entries.async_update_entry(clarification_entry, options=options)
    await hass.async_block_till_done()
    assert hass.states.get("conversation.additional_reader") is not None
    expose(hass, wind_speed=4.44, wind_speed_unit="mph")
    planned, requests = backend
    model_round(planned, [call_event("added-reader", TOOL_NAME, {
        "name": "Test weather", "attributes": ["wind_speed"],
    }), COMPLETED])
    model_round(planned, text_events("The wind speed is 4.44 mph.") + [COMPLETED])
    result = await conversation.async_converse(
        hass, "What is the wind speed from Test weather?", None, Context(),
        language="en", agent_id="conversation.additional_reader",
    )
    assert result.response.speech["plain"]["speech"] == "The wind speed is 4.44 mph."
    assert len([path for path, _ in requests if path.endswith("/responses")]) == 2
    assert not planned


async def test_current_exposure_and_read_permission_are_rechecked(
    hass, clarification_entry, monkeypatch,
):
    expose(hass, wind_speed=4.44)
    assert "attributes" in await read(hass)
    async_expose_entity(hass, "conversation", "weather.test", False)
    assert "error" in await read(hass)
    async_expose_entity(hass, "conversation", "weather.test", True)
    check = SimpleNamespace(check_entity=lambda entity_id, policy: False)
    user = SimpleNamespace(is_active=True, permissions=check)
    monkeypatch.setattr(hass.auth, "async_get_user", AsyncMock(return_value=user))
    assert "error" in await read(hass, context("limited-user"))
    monkeypatch.setattr(hass.auth, "async_get_user", AsyncMock(return_value=None))
    assert "error" in await read(hass, context("deleted-user"))
    user.is_active = False
    monkeypatch.setattr(hass.auth, "async_get_user", AsyncMock(return_value=user))
    assert "error" in await read(hass, context("inactive-user"))


async def test_inaccessible_target_cannot_match_when_other_candidates_exist(
    hass, clarification_entry, monkeypatch,
):
    expose(hass, wind_speed=4.44)
    expose(hass, "weather.other", "Other weather", wind_speed=8)
    async_expose_entity(hass, "conversation", "weather.test", False)
    assert "error" in await read(hass)
    async_expose_entity(hass, "conversation", "weather.test", True)
    user = SimpleNamespace(is_active=True, permissions=SimpleNamespace(
        check_entity=lambda entity_id, policy: entity_id == "weather.other",
    ))
    monkeypatch.setattr(hass.auth, "async_get_user", AsyncMock(return_value=user))
    assert "error" in await read(hass, context("limited-user"))


async def test_missing_and_withheld_fields_remain_read_only_queries(hass, clarification_entry):
    expose(hass, wind_speed=0, media_title="not a weather field")
    data = await read(hass, attributes=["wind_speed", "pressure", "media_title"])
    assert data["attributes"] == {"wind_speed": {"value": 0}}
    assert data["missing"] == ["pressure"]
    assert data["withheld"] == ["media_title"]


async def test_authenticated_caller_alias_and_ambiguity(hass, clarification_entry, hass_admin_user):
    registry = er.async_get(hass)
    entry = registry.async_get_or_create("weather", "test", "alias", original_name="Local readings")
    registry.async_update_entity(entry.entity_id, aliases={"Test weather"})
    expose(hass, entry.entity_id, "Local readings", wind_speed=0, wind_speed_unit="mph")
    data = await read(hass, context(hass_admin_user.id))
    assert data["attributes"]["wind_speed"]["value"] == 0
    expose(hass, "weather.duplicate", "Test weather", wind_speed=99)
    assert "error" in await read(hass)


@pytest.mark.parametrize("state", ["unknown", "unavailable"])
async def test_stale_attributes_are_not_read_when_entity_unavailable(
    hass, clarification_entry, state,
):
    expose(hass, wind_speed=4.44)
    hass.states.async_set("weather.test", state, {
        "friendly_name": "Test weather", "wind_speed": 4.44,
    })
    assert "error" in await read(hass)


@pytest.mark.parametrize("args", [
    {"attributes": ["api_key"]}, {"attributes": []}, {"attributes": ["humidity"] * 9},
    {"service": "turn_off"}, {"name": ""}, {"domain": "weather"},
])
async def test_invalid_arguments_cannot_trigger_reads_or_services(hass, clarification_entry, args):
    with pytest.raises(schema.Invalid):
        await read(hass, **args)


@pytest.mark.parametrize("change", [
    {"platform": "other_agent"}, {"assistant": "other_assistant"}, {"context": None},
])
async def test_unrelated_or_missing_context_has_no_tool(hass, clarification_entry, change):
    ctx = replace(context(), **change)
    assert async_get_tools(hass, ctx, llm.LLM_API_ASSIST) is None
    assert "error" in await read(hass, ctx)
    assert async_get_tools(hass, context(), "other_api") is None
