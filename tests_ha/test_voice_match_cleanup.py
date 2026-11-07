"""Cleanup is an advisory dependency report, never an automatic registry edit."""

import sys
from types import ModuleType, SimpleNamespace

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist import DOMAIN
from custom_components.codex_assist.learning.const import CONF_CONTROL_STT
from custom_components.codex_assist.voice_match import (
    CONF_CLEAN_TRANSCRIPT,
    CONF_PERSONAL_STT_SOURCE,
    CONF_VOICE_MATCH_HOST,
)
from custom_components.codex_assist.voice_match_cleanup import cleanup_report
from tests_ha.test_clean_voice_setup import discovered as discovered


@pytest.fixture(autouse=True)
def no_audio_processing(monkeypatch):
    class UnusedProcessor:
        def __init__(self, *args, **kwargs):
            raise AssertionError("No audio processing in a dependency report")

    for name, attr in (("pymicro_vad", "MicroVad"), ("pyspeex_noise", "AudioProcessor")):
        module = ModuleType(name)
        setattr(module, attr, UnusedProcessor)
        monkeypatch.setitem(sys.modules, name, module)


@pytest.mark.parametrize("dependency", ["none", "pipeline", "legacy", "learning", "other_host"])
async def test_cleanup_reports_dependencies_without_disabling(
    hass, discovered, monkeypatch, dependency,
):
    from homeassistant.components import assist_pipeline

    entity_id = discovered.registered.entity_id
    pipelines = [SimpleNamespace(stt_engine=entity_id)] if dependency == "pipeline" else []
    monkeypatch.setattr(assist_pipeline, "async_get_pipelines", lambda _hass: pipelines)
    if dependency in {"legacy", "learning"}:
        key = CONF_PERSONAL_STT_SOURCE if dependency == "legacy" else CONF_CONTROL_STT
        other = MockConfigEntry(domain=DOMAIN, data={}, options={key: entity_id})
        other.add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={
        CONF_VOICE_MATCH_HOST: ("other.invalid" if dependency == "other_host"
                               else "synthetic.invalid"),
        CONF_CLEAN_TRANSCRIPT: True,
    })
    report = cleanup_report(hass, entry)
    if dependency == "other_host":
        assert entity_id not in report
    elif dependency == "none":
        assert entity_id in report and "No known" in report
    else:
        assert entity_id in report and "Still referenced" in report
    assert discovered.registry.async_get(entity_id).disabled_by is None


async def test_cleanup_requires_direct_setup_and_live_assistant_inventory(hass, monkeypatch):
    from homeassistant.components import assist_pipeline

    entry = MockConfigEntry(domain=DOMAIN, data={})
    assert "still needed" in cleanup_report(hass, entry)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={
        CONF_VOICE_MATCH_HOST: "synthetic.invalid", CONF_CLEAN_TRANSCRIPT: True,
    })

    def unavailable(_hass):
        raise KeyError

    monkeypatch.setattr(assist_pipeline, "async_get_pipelines", unavailable)
    assert "Leave existing sources enabled" in cleanup_report(hass, entry)
