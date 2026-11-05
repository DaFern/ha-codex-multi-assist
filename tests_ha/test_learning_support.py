"""Older Codex support must not accidentally claim newer learning API support."""

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist import DOMAIN
from custom_components.codex_assist.entry_modules import learning_supported


async def test_older_ha_rejects_learning_entry_before_connecting_to_bridge(hass):
    if learning_supported():
        pytest.skip("Negative contract runs on the older HA matrix entries")
    entry = MockConfigEntry(domain=DOMAIN, data={"module": "voice_match"})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert "2026.10" in entry.reason
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "learning_requires_current_ha"
