import importlib
import sys
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from tests.ha_fakes import install_homeassistant_fakes


@pytest.mark.asyncio
async def test_pairing_options_preserve_agents_and_task_prompt_and_hide_saved_key(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    module = importlib.reload(importlib.import_module("custom_components.codex_assist.config_flow"))
    monkeypatch.setattr(
        "custom_components.codex_assist.entry_modules.learning_supported", lambda: True,
    )

    async def backend(_hass, _options):
        return SimpleNamespace(available=True)

    monkeypatch.setitem(sys.modules, "custom_components.codex_assist.voice_match_backend",
                        SimpleNamespace(async_backend=backend))
    key = Fernet.generate_key().decode()
    flow = module.CodexAssistOptionsFlow()
    flow.hass = None
    flow.config_entry = SimpleNamespace(
        options={"agents": [{"id": "primary"}], "prompt": "AI Task prompt"}
    )
    result = await flow.async_step_voice_match({
        "enabled": True, "voice_match_pairing_key": key, "voice_match_host": "synthetic.invalid",
    })
    assert result["data"]["agents"] == [{"id": "primary"}]
    assert result["data"]["prompt"] == "AI Task prompt"
    flow.config_entry.options = result["data"]
    form = await flow.async_step_voice_match()
    assert key not in repr(form)
    result = await flow.async_step_voice_match({"enabled": False})
    assert "voice_match_pairing_key" not in result["data"]
    assert result["data"]["prompt"] == "AI Task prompt"


@pytest.mark.asyncio
async def test_invalid_pairing_key_is_not_saved(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    module = importlib.reload(importlib.import_module("custom_components.codex_assist.config_flow"))
    flow = module.CodexAssistOptionsFlow()
    flow.config_entry = SimpleNamespace(options={})
    result = await flow.async_step_voice_match(
        {"enabled": True, "voice_match_pairing_key": "not-a-key"}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_voice_match_pairing_key"
