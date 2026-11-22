"""Optional modern tools cannot make older HA imports or denials permissive."""

from types import SimpleNamespace

import pytest

from custom_components.codex_assist.satellite_runtime import satellite_tools_supported
from tests.ha_fakes import install_homeassistant_fakes

CAPABILITIES = (
    "API", "APIInstance", "Tool", "ToolResult", "ToolAnnotations",
    "IntentTool", "async_register_api", "async_get_api",
)


@pytest.mark.parametrize("missing", [None, "probatio", *CAPABILITIES])
def test_every_native_capability_is_required(monkeypatch, missing):
    install_homeassistant_fakes(monkeypatch)
    from homeassistant.helpers import config_validation as cv
    from homeassistant.helpers import llm

    cv.probatio = object()
    for name in CAPABILITIES:
        setattr(llm, name, object())
    if missing == "probatio":
        del cv.probatio
    elif missing:
        delattr(llm, missing)
    assert satellite_tools_supported() is (missing is None)


def test_api_registration_alone_never_enables_satellite_tools(monkeypatch):
    install_homeassistant_fakes(monkeypatch)
    from homeassistant.helpers import llm

    llm.API = object()
    llm.async_register_api = object()
    assert not satellite_tools_supported()


@pytest.mark.asyncio
@pytest.mark.parametrize("step", [
    "music", "neutral_satellite", "guest", "room_music_defaults", "room_music_default",
    "room_music_continue", "room_music_save",
])
async def test_unsupported_options_cannot_be_saved(monkeypatch, step):
    import importlib

    install_homeassistant_fakes(monkeypatch)
    config_flow = importlib.reload(
        importlib.import_module("custom_components.codex_assist.config_flow")
    )
    entry = SimpleNamespace(data={}, options={"preserved": True})
    flow = config_flow.CodexAssistOptionsFlow()
    flow.config_entry = entry
    result = await getattr(flow, f"async_step_{step}")({"unexpected": "input"})
    assert result == {"type": "abort", "reason": "satellite_requires_current_ha"}
    assert entry.options == {"preserved": True}
