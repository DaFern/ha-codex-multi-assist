"""Guest role options use HA's supported editor without changing RBAC roles."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist.guest_policy import CONF_GUEST_ROLE
from custom_components.codex_assist.satellite_runtime import satellite_tools_supported


async def test_guest_role_options_revalidate_and_preserve_unrelated_settings(hass, monkeypatch):
    from custom_components.codex_assist import config_flow

    entry = MockConfigEntry(
        domain="codex_assist", data={}, options={"prompt": "preserve", "music_player_ids": []},
    )
    entry.add_to_hass(hass)
    choices = AsyncMock(return_value={"voice_guest": "Guest voice"})
    monkeypatch.setattr(config_flow, "async_guest_role_choices", choices)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    if not satellite_tools_supported():
        assert "guest" not in result["menu_options"]
        choices.assert_not_awaited()
        assert CONF_GUEST_ROLE not in entry.options
        return
    assert "guest" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "guest"},
    )
    assert result["type"] is FlowResultType.FORM
    assert CONF_GUEST_ROLE not in entry.options
    choices.return_value = {}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_GUEST_ROLE: "voice_guest"},
    )
    assert result["errors"] == {"base": "invalid_guest_role"}
    assert CONF_GUEST_ROLE not in entry.options
    choices.return_value = {"voice_guest": "Guest voice"}
    # The redisplayed picker contained Disabled only. HA must not accept the
    # restored role through that stale schema; reopen instead of weakening it.
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_GUEST_ROLE: "voice_guest"},
        )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_GUEST_ROLE: ""},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "guest"},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_GUEST_ROLE: "voice_guest"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {
        "prompt": "preserve", "music_player_ids": [], CONF_GUEST_ROLE: "voice_guest",
    }
    choices.return_value = None
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "guest"},
    )
    assert result["errors"] == {"base": "guest_policy_unavailable"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_GUEST_ROLE: ""},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {"prompt": "preserve", "music_player_ids": []}


async def test_experimental_satellite_enrollment_is_explicit_and_registry_checked(
    hass, monkeypatch,
):
    from homeassistant.helpers import entity_registry as er

    from custom_components.codex_assist import config_flow

    if not satellite_tools_supported():
        pytest.skip("Experimental routing requires modern HA")
    entry = MockConfigEntry(domain="codex_assist", data={}, options={"prompt": "preserve"})
    entry.add_to_hass(hass)
    esphome = MockConfigEntry(domain="esphome")
    esphome.add_to_hass(hass)
    satellite = er.async_get(hass).async_get_or_create(
        "assist_satellite", "esphome", "synthetic", config_entry=esphome,
    )
    monkeypatch.setattr(config_flow, "async_guest_role_choices",
                        AsyncMock(return_value={"guest": "Guest"}))

    async def form():
        result = await hass.config_entries.options.async_init(entry.entry_id)
        return await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "guest"},
        )

    result = await form()
    assert "protected_satellite_ids" not in entry.options
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        CONF_GUEST_ROLE: "guest", "protected_satellite_ids": ["assist_satellite.missing"],
    })
    assert result["errors"] == {"base": "invalid_protected_satellites"}
    assert dict(entry.options) == {"prompt": "preserve"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        CONF_GUEST_ROLE: "guest", "protected_satellite_ids": [satellite.entity_id],
    })
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {
        "prompt": "preserve", CONF_GUEST_ROLE: "guest",
        "protected_satellite_ids": [satellite.entity_id],
    }
    result = await form()
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        CONF_GUEST_ROLE: "", "protected_satellite_ids": [],
    })
    assert dict(entry.options) == {"prompt": "preserve"}
