"""Music-only native LLM API for verified Assist satellite requests."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from homeassistant.helpers import llm

from .music_control import (
    MUSIC_API_ID,
    MusicAuthorization,
    MusicControlTool,
    current_music_authorization,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class MusicControlAPI(llm.API):
    """Expose only the bounded music tool, never the general Assist tool set."""

    @override
    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        authorization: MusicAuthorization | None = current_music_authorization()
        tools = []
        if (
            authorization is not None
            and authorization.context is llm_context.context
            and authorization.prepared_request.verified
            and authorization.prepared_request.voice
            and authorization.user_id == authorization.prepared_request.ha_user_id
        ):
            tools = [MusicControlTool(authorization)]
        return llm.APIInstance(
            api=self,
            api_prompt=(
                "This request has access to one music-only Home Assistant tool. "
                "Use it only for Music Assistant playback, transport, volume, and queue "
                "requests. Pass a named room as room; the tool applies its saved default. "
                "Only pass speaker when the user explicitly names a particular player. "
                "If the tool cannot select a player, ask rather than choosing another. "
                "For a search with several plausible matches, ask the user before playing. "
                "Never use or claim access to other Home Assistant entities."
            ),
            llm_context=llm_context,
            tools=tools,
        )


def async_register_music_api(hass: HomeAssistant):
    """Register the per-request music-only API."""
    return llm.async_register_api(
        hass,
        MusicControlAPI(
            hass=hass,
            id=MUSIC_API_ID,
            name="Codex Assist Music",
        ),
    )
