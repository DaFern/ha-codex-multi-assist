"""Fail-closed guest-provider boundary and admin role selection."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.codex_assist import guest_policy
from tests.ha_fakes import install_homeassistant_fakes


@pytest.mark.parametrize("version", [None, 0, 2, True, "1"])
async def test_missing_or_incompatible_guest_provider_cannot_grant(monkeypatch, version):
    api = SimpleNamespace(GUEST_POLICY_VERSION=version, async_check_guest_action=AsyncMock())
    monkeypatch.setattr(guest_policy, "import_module", lambda _: api)
    assert not await guest_policy.async_check_guest_action(
        object(), "guest", ("light.test",), operation="turn_on",
    )
    assert await guest_policy.async_guest_role_choices(object()) is None
    api.async_check_guest_action.assert_not_awaited()


@pytest.mark.parametrize("allowed", [False, "true", 1, None])
async def test_truthy_or_malformed_provider_result_is_not_authority(monkeypatch, allowed):
    api = SimpleNamespace(
        GUEST_POLICY_VERSION=1,
        async_check_guest_action=AsyncMock(return_value=SimpleNamespace(allowed=allowed)),
    )
    monkeypatch.setattr(guest_policy, "import_module", lambda _: api)
    assert not await guest_policy.async_check_guest_action(
        object(), "guest", ("light.test",), operation="turn_on",
    )


@pytest.mark.parametrize("roles", [
    [{"id": "guest", "name": "Guest"}, {"id": "guest", "name": "Duplicate"}],
    [{"id": "guest", "name": "Guest", "rules": {}}],
    [{"id": "", "name": "Guest"}],
    [{"id": "guest", "name": "bad\nname"}],
])
async def test_role_picker_rejects_malformed_metadata(monkeypatch, roles):
    api = SimpleNamespace(
        GUEST_POLICY_VERSION=1,
        async_guest_role_choices=AsyncMock(return_value={"available": True, "roles": roles}),
    )
    monkeypatch.setattr(guest_policy, "import_module", lambda _: api)
    assert await guest_policy.async_guest_role_choices(object()) is None


@pytest.fixture
def options(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    module = importlib.reload(importlib.import_module("custom_components.codex_assist.config_flow"))
    monkeypatch.setattr(module, "satellite_tools_supported", lambda: True)
    roles = AsyncMock(return_value={"guest": "Guest"})
    monkeypatch.setattr(module, "async_guest_role_choices", roles)
    entry = SimpleNamespace(data={}, options={"prompt": "keep", "music_player_ids": ["player"]})
    flow = module.CodexAssistOptionsFlow()
    flow.config_entry = entry
    flow.hass = object()
    return flow, entry, roles


async def test_opening_guest_setup_does_not_grant_or_write_anything(options):
    flow, entry, roles = options
    result = await flow.async_step_guest()
    assert result["type"] == "form"
    assert result["errors"] == {}
    assert guest_policy.CONF_GUEST_ROLE not in entry.options
    roles.assert_awaited_once()


async def test_selection_and_disable_preserve_every_unrelated_option(options):
    flow, entry, roles = options
    result = await flow.async_step_guest({guest_policy.CONF_GUEST_ROLE: "guest"})
    assert result == {
        "type": "create_entry", "title": "",
        "data": {**entry.options, guest_policy.CONF_GUEST_ROLE: "guest"},
    }
    entry.options = result["data"]
    roles.return_value = None
    result = await flow.async_step_guest({guest_policy.CONF_GUEST_ROLE: ""})
    assert result["data"] == {"prompt": "keep", "music_player_ids": ["player"]}


@pytest.mark.parametrize("selected", ["missing", True, [], {}])
async def test_unknown_or_invalid_role_cannot_be_saved(options, selected):
    flow, entry, _ = options
    result = await flow.async_step_guest({guest_policy.CONF_GUEST_ROLE: selected})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_guest_role"}
    assert guest_policy.CONF_GUEST_ROLE not in entry.options


async def test_removed_role_or_provider_failure_never_saves_a_cached_choice(options):
    flow, entry, roles = options
    await flow.async_step_guest()
    roles.return_value = None
    result = await flow.async_step_guest({guest_policy.CONF_GUEST_ROLE: "guest"})
    assert result["type"] == "form"
    assert guest_policy.CONF_GUEST_ROLE not in entry.options
