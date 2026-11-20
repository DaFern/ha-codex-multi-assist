"""Neutral satellite access stays bound to verified packets and selected targets."""

import pytest
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import intent, llm
from homeassistant.setup import async_setup_component

from custom_components.codex_assist.satellite_runtime import satellite_tools_supported

if not satellite_tools_supported():
    pytest.skip("Satellite tools require HA's modern native tool contract", allow_module_level=True)

from custom_components.codex_assist import satellite_access
from custom_components.codex_assist.satellite_access import (
    AllowedAssistIntentTool,
    AllowedEntityContextTool,
    NeutralAuthorization,
    NeutralSatelliteAPI,
    neutral_authorization,
)
from custom_components.codex_assist.voice_match import PreparedRequest


@pytest.fixture(autouse=True)
async def native_intents(hass):
    """Register real native handlers instead of assuming a bare hass has them."""
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "intent", {})


def _llm_context(context, *, device_id="test-device"):
    return llm.LLMContext(
        platform="codex_assist",
        context=context,
        language="en",
        assistant="conversation",
        device_id=device_id,
    )


def _authorization(context, entity_ids, *, verified=True, voice=None, user_id=None):
    return NeutralAuthorization(
        context=context,
        prepared_request=PreparedRequest(
            "turn on the light", "", object(), None,
            verified=verified, voice=voice, ha_user_id=user_id,
        ),
        satellite_id="assist_satellite.test",
        entity_ids=tuple(entity_ids),
    )


def _entity(hass, domain, object_id, state="off"):
    entity_id = f"{domain}.{object_id}"
    er.async_get(hass).async_get_or_create(
        domain, "test", object_id, suggested_object_id=object_id,
    )
    hass.states.async_set(entity_id, state, {"friendly_name": object_id.title()})
    async_expose_entity(hass, "conversation", entity_id, True)
    return entity_id


@pytest.mark.parametrize(
    "verified,voice,user_id",
    [(False, None, None), (True, "matched", "user"), (True, None, "user")],
)
async def test_neutral_api_fails_closed_for_non_neutral_authority(
    hass, verified, voice, user_id,
):
    context = Context()
    _entity(hass, "assist_satellite", "test")
    _entity(hass, "light", "allowed")
    auth = _authorization(
        context, ("light.allowed",), verified=verified, voice=voice, user_id=user_id,
    )
    api = NeutralSatelliteAPI(hass=hass, id="neutral", name="Neutral")

    with neutral_authorization(auth):
        instance = await api.async_get_api_instance(_llm_context(context))

    assert instance.tools == []


async def test_neutral_api_exposes_only_scoped_read_and_native_intent_tools(
    hass, monkeypatch,
):
    context = Context()
    _entity(hass, "assist_satellite", "test")
    _entity(hass, "light", "allowed")
    monkeypatch.setattr(
        satellite_access,
        "async_should_expose",
        lambda _hass, _assistant, entity_id: entity_id == "light.allowed",
    )
    auth = _authorization(context, ("light.allowed",))
    api = NeutralSatelliteAPI(hass=hass, id="neutral", name="Neutral")

    with neutral_authorization(auth):
        instance = await api.async_get_api_instance(_llm_context(context))

    names = {tool.name for tool in instance.tools}
    assert "codex_assist__neutral__GetLiveContext" in names
    assert any(name.endswith("__HassTurnOn") for name in names)
    assert all("MCP" not in name for name in names)


async def test_neutral_intent_executes_only_selected_native_targets(hass, monkeypatch):
    context = Context()
    _entity(hass, "assist_satellite", "test")
    allowed = _entity(hass, "light", "allowed")
    denied = _entity(hass, "light", "denied")
    exposed = {allowed, denied}
    monkeypatch.setattr(
        satellite_access,
        "async_should_expose",
        lambda _hass, _assistant, entity_id: entity_id in exposed,
    )
    calls = []

    async def turn_on(call):
        calls.append((call.data["entity_id"], call.context))

    hass.services.async_register("light", "turn_on", turn_on)
    handler = intent.ServiceIntentHandler(
        "HassTurnOn", domain="light", service="turn_on",
        required_domains={"light"},
    )
    auth = _authorization(context, (allowed,))
    tool = AllowedAssistIntentTool(handler, auth)
    input_context = _llm_context(context)

    result = await tool.async_call(
        hass,
        llm.ToolInput(tool_name=tool.name, tool_args={"name": allowed}),
        input_context,
    )

    assert result.error is False
    assert calls == [(allowed, context)]


async def test_neutral_intent_rejects_mixed_allowed_and_unallowed_targets(hass, monkeypatch):
    context = Context()
    _entity(hass, "assist_satellite", "test")
    allowed = _entity(hass, "light", "allowed")
    denied = _entity(hass, "light", "denied")
    monkeypatch.setattr(
        satellite_access,
        "async_should_expose",
        lambda _hass, _assistant, entity_id: entity_id in {allowed, denied},
    )
    calls = []

    async def turn_on(call):
        calls.append(call.data["entity_id"])

    hass.services.async_register("light", "turn_on", turn_on)
    handler = intent.ServiceIntentHandler(
        "HassTurnOn", domain="light", service="turn_on",
        required_domains={"light"},
    )
    auth = _authorization(context, (allowed,))
    tool = AllowedAssistIntentTool(handler, auth)

    result = await tool.async_call(
        hass,
        llm.ToolInput(
            tool_name=tool.name,
            tool_args={"name": "all", "domain": ["light"]},
        ),
        _llm_context(context),
    )

    assert result.error is True
    assert calls == []


async def test_neutral_intent_rejects_a_different_context(hass):
    context = Context()
    _entity(hass, "assist_satellite", "test")
    allowed = _entity(hass, "light", "allowed")
    handler = intent.ServiceIntentHandler(
        "HassTurnOn", domain="light", service="turn_on",
        required_domains={"light"},
    )
    auth = _authorization(context, (allowed,))
    tool = AllowedAssistIntentTool(handler, auth)

    result = await tool.async_call(
        hass,
        llm.ToolInput(tool_name=tool.name, tool_args={"name": allowed}),
        _llm_context(Context()),
    )

    assert result.error is True


async def test_neutral_live_context_returns_only_selected_entities(hass, monkeypatch):
    context = Context()
    allowed = _entity(hass, "light", "allowed", "on")
    denied = _entity(hass, "sensor", "private", "secret")
    monkeypatch.setattr(
        satellite_access,
        "async_should_expose",
        lambda _hass, _assistant, _entity_id: True,
    )
    auth = _authorization(context, (allowed,))
    tool = AllowedEntityContextTool(auth)

    result = await tool.async_call(
        hass,
        llm.ToolInput(tool_name=tool.name, tool_args={}),
        _llm_context(context),
    )

    assert result.error is False
    assert [entity["entity_id"] for entity in result.data["entities"]] == [allowed]
    assert denied not in {entity["entity_id"] for entity in result.data["entities"]}
