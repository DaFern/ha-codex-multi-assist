"""Cached endpoint hints never export options or establish pairing authority."""

import sys
import types
from types import SimpleNamespace

import pytest

from custom_components.codex_assist.learning.discovery import (
    origins_from_metadata,
    suggested_origins,
)
from tests.ha_fakes import install_homeassistant_fakes


def addon(**kwargs):
    return {
        "name": "Wyoming Voice Match",
        "hostname": "test-voice-match",
        "ingress_port": 8099,
        "options": {"password": "PRIVATE-options", "key": "PRIVATE-key"},
        **kwargs,
    }


def test_discovery_only_returns_origins_and_deduplicates():
    result = origins_from_metadata(
        {
            "repo_voice_match": addon(),
            "other_voice_match": addon(),
            "unrelated": addon(hostname="wrong"),
        }
    )
    assert result == ["http://test-voice-match:8099"]
    assert "PRIVATE" not in str(result)


@pytest.mark.parametrize(
    "change",
    [
        {"hostname": "user:password@host"},
        {"hostname": "host/path"},
        {"hostname": "bad?query"},
        {"hostname": "host:8099"},
        {"hostname": "host\n"},
        {"hostname": ""},
        {"ingress_port": True},
        {"ingress_port": None},
        {"ingress_port": "8099"},
        {"ingress_port": 70000},
        {"name": "Other app"},
    ],
)
def test_malformed_metadata_is_not_suggested(change):
    assert origins_from_metadata({"repo_voice_match": addon(**change)}) == []


def test_no_supervisor_retains_manual_setup_without_importing_it():
    assert suggested_origins(SimpleNamespace(config=SimpleNamespace(components=set()))) == []
    assert origins_from_metadata(None) == []


@pytest.mark.parametrize("ready", [True, False])
def test_supported_supervisor_cache_is_used_without_network_or_credentials(monkeypatch, ready):
    install_homeassistant_fakes(monkeypatch)
    module = types.ModuleType("homeassistant.components.hassio")

    class NotReady(Exception):
        pass

    calls = []

    def cached(hass):
        calls.append(hass)
        if not ready:
            raise NotReady
        return {"repo_voice_match": addon()}

    module.HassioNotReadyError = NotReady
    module.get_addons_info = cached
    monkeypatch.setitem(sys.modules, module.__name__, module)
    hass = SimpleNamespace(config=SimpleNamespace(components={"hassio"}))
    result = suggested_origins(hass)
    assert calls == [hass]
    assert result == (["http://test-voice-match:8099"] if ready else [])
    assert "PRIVATE" not in str(result)
