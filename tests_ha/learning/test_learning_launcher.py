"""Native HA discovery and panel registration, without opening a real microphone."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import test_phone_learning_pipeline as phone_fixtures
from homeassistant.auth.models import TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN
from homeassistant.components import frontend
from homeassistant.helpers import entity_registry as er

from custom_components.codex_assist.learning import DOMAIN
from custom_components.codex_assist.learning.learning_bridge_protocol import (
    BridgeError,
)

phone = phone_fixtures.phone
phone_probe = phone_fixtures.phone_probe


async def discover(phone, **extra):
    await phone["client"].send_json(
        {"id": 8000, "type": DOMAIN + "/voice_learning/launch_info", **extra}
    )
    return await phone["client"].receive_json()


async def test_launcher_is_non_iframe_panel_and_discovery_is_read_only(hass, phone):
    from homeassistant.components import assist_pipeline

    panels = hass.data[frontend.DATA_PANELS]
    panel = panels["voice-match-learning"]
    assert panel.require_admin is False
    assert panel.sidebar_title is None
    assert panel.config["_panel_custom"]["embed_iframe"] is False
    before = list(phone["backend"].calls)
    result = await discover(phone)
    assert result["success"], result
    assert result["result"] == {
        "user_id": phone["backend"].user_id,
        "profile_id": "assigned-profile",
        "pipeline_id": next(
            p.id
            for p in assist_pipeline.async_get_pipelines(hass)
            if p.stt_engine == phone["engine"].entity_id
        ),
    }
    assert [call[0] for call in phone["backend"].calls[len(before) :]] == ["own_profile"]
    assert not phone["backend"].active
    assert phone["runtime"].controller.flows == {}


async def test_launcher_asset_is_served_without_pairing_or_recording_secrets(hass_client, phone):
    client = await hass_client()
    response = await client.get("/codex_assist/voice-learning-launch-v1.js")
    assert response.status == 200
    source = await response.text()
    assert 'type: "assist/show"' in source
    assert "session_token" not in source
    assert "learning_bridge_key" not in source


async def test_launcher_registration_never_overwrites_an_existing_panel(hass, phone):
    from custom_components.codex_assist.learning.launcher import register_panel

    original = hass.data[frontend.DATA_PANELS]["voice-match-learning"]
    await register_panel(hass)
    assert hass.data[frontend.DATA_PANELS]["voice-match-learning"] is original


@pytest.mark.parametrize(
    "extra",
    [
        {"user_id": "other"},
        {"profile_id": "other"},
        {"pipeline_id": "other"},
        {"consent": True},
        {"session_token": "synthetic"},
    ],
)
async def test_launch_discovery_never_accepts_client_scope_or_consent(phone, extra):
    before = list(phone["backend"].calls)
    result = await discover(phone, **extra)
    assert not result["success"]
    assert phone["backend"].calls == before


async def test_launch_requires_own_profile_even_for_admin(phone):
    original = phone["runtime"].controller.bridge.call

    async def no_profile(operation, user_id, data):
        if operation == "own_profile":
            return {"id": None}
        return await original(operation, user_id, data)

    with patch.object(phone["runtime"].controller.bridge, "call", side_effect=no_profile):
        result = await discover(phone)
    assert result["error"]["code"] == "own_profile_required"
    assert not phone["backend"].active


@pytest.mark.parametrize(
    "problem",
    ["missing", "duplicate", "wrong_agent", "unavailable", "closing", "multiple_companions"],
)
async def test_launch_rejects_ambiguous_missing_or_unavailable_learning_setup(hass, phone, problem):
    from homeassistant.components import assist_pipeline

    pipelines = assist_pipeline.async_get_pipelines(hass)
    expected = next(p for p in pipelines if p.stt_engine == phone["engine"].entity_id)
    if problem == "unavailable":
        hass.states.async_set(phone["engine"].entity_id, "unavailable")
    elif problem == "closing":
        phone["runtime"].controller.closing = True
    elif problem == "multiple_companions":
        from custom_components.codex_assist.learning import launcher
        from custom_components.codex_assist.learning.lifecycle import LearningRuntime

        other = SimpleNamespace(entry_id="other-test-entry")
        original = launcher.loaded_runtime

        def lookup(hass, entry_id):
            if entry_id == other.entry_id:
                return LearningRuntime(
                    phone["entry"].runtime_data.module,
                    (),
                    None,
                    SimpleNamespace(controller=SimpleNamespace(closing=False)),
                )
            return original(hass, entry_id)

    choices = {
        "missing": [],
        "duplicate": [expected, replace(expected, id="duplicate")],
        "wrong_agent": [replace(expected, conversation_engine="conversation.home_assistant")],
    }
    try:
        from contextlib import ExitStack

        with ExitStack() as stack:
            if problem == "multiple_companions":
                stack.enter_context(patch.object(launcher, "loaded_runtime", side_effect=lookup))
                entries = hass.config_entries.async_entries(DOMAIN)
                stack.enter_context(
                    patch.object(
                        hass.config_entries, "async_entries", return_value=[*entries, other]
                    )
                )
            stack.enter_context(
                patch(
                    "homeassistant.components.assist_pipeline.async_get_pipelines",
                    return_value=choices.get(problem, pipelines),
                )
            )
            result = await discover(phone)
        assert result["error"]["code"] == "not_ready"
    finally:
        phone["runtime"].controller.closing = False


async def test_pipeline_resolution_follows_registry_renames_not_display_names(hass, phone):
    from homeassistant.components import assist_pipeline

    registry = er.async_get(hass)
    old_id = phone["engine"].entity_id
    registry.async_update_entity(old_id, new_entity_id="stt.renamed_learning")
    await hass.async_block_till_done()
    pipelines = assist_pipeline.async_get_pipelines(hass)
    expected = next(p for p in pipelines if p.stt_engine == old_id)
    with patch(
        "homeassistant.components.assist_pipeline.async_get_pipelines",
        return_value=[
            replace(expected, stt_engine="stt.renamed_learning", name="A different name")
        ],
    ):
        assert (await discover(phone))["success"]


async def test_launch_rechecks_login_after_authorised_profile_read(hass, phone):
    original = phone["runtime"].authorize
    checks = 0

    def revoked(connection, user_id):
        nonlocal checks
        checks += 1
        if checks == 2:
            raise ValueError("Synthetic revoked login")
        return original(connection, user_id)

    with patch.object(phone["runtime"], "authorize", side_effect=revoked):
        result = await discover(phone)
    assert checks == 2
    assert result["error"]["code"] == "not_ready"


async def test_long_lived_login_cannot_discover_or_grant_phone_launch(
    hass, hass_ws_client, hass_admin_user, phone
):
    token = await hass.auth.async_create_refresh_token(
        hass_admin_user,
        token_type=TOKEN_TYPE_LONG_LIVED_ACCESS_TOKEN,
        client_name="Synthetic launcher test",
    )
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(token))
    await client.send_json({"id": 8001, "type": DOMAIN + "/voice_learning/launch_info"})
    result = await client.receive_json()
    assert result["error"]["code"] == "not_ready"
    assert not [call for call in phone["backend"].calls if call[0] == "own_profile"]


async def test_bridge_failure_and_malformed_profile_never_leak_peer_data(phone):
    bridge = phone["runtime"].controller.bridge
    for value in ([], {"id": "bad/profile"}, {"id": True}):
        with patch.object(bridge, "call", return_value=value):
            result = await discover(phone)
        assert not result["success"]
    with patch.object(bridge, "call", side_effect=BridgeError("synthetic-peer-secret")):
        result = await discover(phone)
    assert "synthetic-peer-secret" not in str(result)
    assert not result["success"]
