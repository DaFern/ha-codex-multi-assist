"""Real-HA framework contracts, separate from the add-on unit suite."""

from unittest.mock import patch

import pytest
from homeassistant.setup import async_setup_component


@pytest.fixture(autouse=True)
def frontend_assets(tmp_path):
    """Isolated HA lacks bundled frontend assets; keep real panel/HTTP APIs.

    This replaces only the asset directory, not frontend setup, panel registration
    or the launcher's production JS. Native Android behaviour remains a phone test.
    """
    from custom_components.codex_assist.entry_modules import learning_supported

    if not learning_supported():
        pytest.skip("Learning retains its existing Home Assistant 2026.10+ requirement")
    from homeassistant.components import frontend

    root = tmp_path / "frontend-assets"
    root.mkdir()
    for name in ("static", "frontend_latest", "frontend_es5"):
        (root / name).mkdir()
    for name in (
        "service_worker.js",
        "sw-modern.js",
        "sw-modern.js.map",
        "sw-legacy.js",
        "sw-legacy.js.map",
        "robots.txt",
        "onboarding.html",
        "authorize.html",
        "index.html",
    ):
        (root / name).write_text("")
    with patch.object(frontend, "_frontend_root", return_value=root):
        yield


@pytest.fixture(autouse=True)
async def enable_companion(enable_custom_integrations, hass):
    assert await async_setup_component(hass, "homeassistant", {})
    yield
