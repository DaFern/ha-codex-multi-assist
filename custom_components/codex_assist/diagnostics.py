"""Diagnostics support for Codex Assist."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

REDACTED = "**REDACTED**"
TO_REDACT = {
    "access_token", "refresh_token", "prompt", "voice_match_pairing_key",
    "key", "pairing_key", "learning_bridge_key", "personalisation_key",
    "personal_instructions", "instructions", "session_token", "capability",
    "user_id", "voice_id", "profile_id", "url", "host",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return redacted diagnostics for a Codex Assist config entry."""
    del hass
    return {
        "entry": {
            "data": redact_sensitive(dict(entry.data)),
            "options": redact_sensitive(dict(entry.options)),
        },
    }


def redact_sensitive(data: Any) -> Any:
    """Redact module credentials and personal content at every nesting level."""
    if isinstance(data, Mapping):
        return {
            key: REDACTED if key in TO_REDACT else redact_sensitive(value)
            for key, value in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [redact_sensitive(value) for value in data]
    return data
