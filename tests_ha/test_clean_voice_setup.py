"""Native options/registry contracts with synthetic external engine metadata."""

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from homeassistant.components import stt
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist import DOMAIN
from custom_components.codex_assist.entry_modules import learning_supported
from custom_components.codex_assist.voice_match import (
    CONF_CLEAN_TRANSCRIPT,
    CONF_PERSONAL_STT_SOURCE,
    CONF_VOICE_MATCH_KEY,
)
from custom_components.codex_assist.voice_match_stt import resolve_personal_source


@pytest.fixture
async def discovered(hass, monkeypatch):
    assert await async_setup_component(hass, "stt", {})
    entry = MockConfigEntry(domain="wyoming", data={})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registered = registry.async_get_or_create(
        "stt", "wyoming", "synthetic-personal", config_entry=entry,
        suggested_object_id="synthetic_personal",
    )
    engine = SimpleNamespace(
        available=True, platform=SimpleNamespace(platform_name="wyoming"),
        service=SimpleNamespace(info=SimpleNamespace(asr=[
            SimpleNamespace(name="voice-match-personal"),
        ])),
    )
    monkeypatch.setattr(stt, "async_get_speech_to_text_entity",
                        lambda _hass, entity: engine if entity == registered.entity_id else None)
    return SimpleNamespace(entry=entry, registry=registry, registered=registered, engine=engine)


async def test_personal_source_uses_discovered_service_not_editable_label(hass, discovered):
    p = discovered
    assert resolve_personal_source(hass, p.registered.entity_id) is p.engine
    p.engine.name = "voice-match-personal"
    p.engine.service.info.asr[0].name = "whisper"
    assert resolve_personal_source(hass, p.registered.entity_id) is None


@pytest.mark.parametrize("invalid", ["missing", "disabled", "unavailable", "learning",
                                    "normal", "no_metadata", "wrong_entry", "no_stt"])
async def test_invalid_personal_sources_are_rejected(hass, discovered, invalid, monkeypatch):
    p = discovered
    entity_id = p.registered.entity_id
    if invalid == "missing":
        entity_id = "stt.missing"
    elif invalid == "disabled":
        p.registry.async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.USER)
    elif invalid == "unavailable":
        p.engine.available = False
    elif invalid == "learning":
        p.engine.platform.platform_name = "codex_assist"
    elif invalid == "normal":
        p.engine.service.info.asr[0].name = "voice-match"
    elif invalid == "no_metadata":
        p.engine.service.info.asr = []
    elif invalid == "wrong_entry":
        original = hass.config_entries.async_get_entry
        monkeypatch.setattr(hass.config_entries, "async_get_entry",
                            lambda entry_id: (None if entry_id == p.entry.entry_id
                                              else original(entry_id)))
    else:
        hass.config.components.remove("stt")
    assert resolve_personal_source(hass, entity_id) is None
    assert resolve_personal_source(hass, None) is None
    assert resolve_personal_source(hass, []) is None


async def clean_options(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "clean_voice" in result["menu_options"]
    return await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "clean_voice"},
    )


@pytest.mark.parametrize("saved, expected", [(None, True), (True, True), (False, False)])
async def test_clean_options_default_on_preserves_saved_choice(hass, saved, expected):
    options = {} if saved is None else {CONF_CLEAN_TRANSCRIPT: saved}
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options)
    entry.add_to_hass(hass)
    result = await clean_options(hass, entry)
    enabled = next(field for field in result["data_schema"].schema if field == "enabled")
    assert enabled.default() is expected
    # Opening setup alone must not enable a platform or change existing options.
    assert dict(entry.options) == options


async def test_clean_options_pairing_required(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await clean_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"enabled": True},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == (
        "clean_voice_needs_pairing" if learning_supported() else "clean_voice_requires_current_ha"
    )
    assert not entry.options


async def test_clean_options_save_source_preserve_defaults_and_disable(hass, monkeypatch):
    key = Fernet.generate_key().decode()
    options = {CONF_VOICE_MATCH_KEY: key, "prompt": "Task prompt", "agents": [{"id": "primary"}]}
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options)
    entry.add_to_hass(hass)
    monkeypatch.setattr(
        "custom_components.codex_assist.voice_match_stt.resolve_personal_source",
        lambda _hass, entity: object() if entity == "stt.personal" else None,
    )
    result = await clean_options(hass, entry)
    assert key not in repr(result)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"enabled": True, CONF_PERSONAL_STT_SOURCE: "stt.wrong"},
    )
    if not learning_supported():
        assert result["errors"]["base"] == "clean_voice_requires_current_ha"
        return
    assert result["errors"][CONF_PERSONAL_STT_SOURCE] == "invalid_personal_stt_source"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"enabled": True, CONF_PERSONAL_STT_SOURCE: "stt.personal"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {
        **options, CONF_CLEAN_TRANSCRIPT: True, CONF_PERSONAL_STT_SOURCE: "stt.personal",
    }
    result = await clean_options(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"enabled": False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {**options, CONF_CLEAN_TRANSCRIPT: False}
    result = await clean_options(hass, entry)
    enabled = next(field for field in result["data_schema"].schema if field == "enabled")
    assert enabled.default() is False


async def test_disabling_pairing_also_disables_clean_source(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={
        CONF_VOICE_MATCH_KEY: Fernet.generate_key().decode(),
        CONF_CLEAN_TRANSCRIPT: True, CONF_PERSONAL_STT_SOURCE: "stt.personal", "prompt": "Keep",
    })
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": "voice_match"},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"enabled": False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {"prompt": "Keep"}
