"""Lightweight context marker for native Assist satellite API discovery."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_SATELLITE_ASSIST_ACTIVE: ContextVar[bool] = ContextVar(
    "codex_assist_satellite_assist_active", default=False
)

def satellite_tools_supported() -> bool:
    """Require HA's modern native tool contract, not merely API registration.

    Older HA can register APIs but lacks typed results, annotations and the
    matching schema validator. Never import modern providers or fall back to
    broader Assist authority on that basis.
    """
    from homeassistant.helpers import config_validation as cv
    from homeassistant.helpers import llm

    return hasattr(cv, "probatio") and all(
        hasattr(llm, name)
        for name in (
            "API", "APIInstance", "Tool", "ToolResult", "ToolAnnotations",
            "IntentTool", "async_register_api", "async_get_api",
        )
    )


@contextmanager
def satellite_assist_context() -> Iterator[None]:
    """Mark native satellite Assist API discovery to omit Codex MCP additions."""
    token = _SATELLITE_ASSIST_ACTIVE.set(True)
    try:
        yield
    finally:
        _SATELLITE_ASSIST_ACTIVE.reset(token)


def satellite_assist_active() -> bool:
    """Return whether native Assist API discovery is for a satellite turn."""
    return _SATELLITE_ASSIST_ACTIVE.get()
