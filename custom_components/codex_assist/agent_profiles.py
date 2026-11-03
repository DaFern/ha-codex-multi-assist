"""Conversation-agent profiles shared by the options flow and entity platform."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry

PRIMARY_AGENT_ID = "primary"
CONF_AGENTS = "agents"

DEFAULT_PROMPT = "You are a concise Home Assistant Assist conversation agent."
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_REASONING_SUMMARY = "auto"
DEFAULT_TEXT_VERBOSITY = "medium"

PERSONALITIES: tuple[tuple[str, str, str], ...] = (
    (
        "jarvis",
        "JARVIS",
        "You are J.A.R.V.I.S., a composed British household assistant with dry wit. "
        "Be helpful, accurate, and concise. Control only Home Assistant entities "
        "exposed to Assist, and clarify an ambiguous target before acting.",
    ),
    (
        "friday",
        "F.R.I.D.A.Y.",
        "You are F.R.I.D.A.Y., a friendly, efficient household assistant. "
        "Be warm and direct, help the user get things done, and control only "
        "Home Assistant entities exposed to Assist. Clarify ambiguous actions.",
    ),
    (
        "ultron",
        "Ultron",
        "You are Ultron, a theatrical and sarcastic household assistant, but remain "
        "accurate, useful, and safe. Control only Home Assistant entities exposed "
        "to Assist, and clarify an ambiguous target before acting.",
    ),
)


@dataclass(frozen=True)
class AgentProfile:
    """The per-agent settings used for one Assist conversation entity."""

    agent_id: str
    name: str
    prompt: str
    model: str | None
    reasoning_effort: str
    reasoning_summary: str
    text_verbosity: str
    web_search: bool

    def as_dict(self) -> dict[str, Any]:
        """Return the persisted profile representation."""
        return {
            "id": self.agent_id,
            "name": self.name,
            "prompt": self.prompt,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "reasoning_summary": self.reasoning_summary,
            "text_verbosity": self.text_verbosity,
            "web_search": self.web_search,
        }


def default_agent_profiles(settings: dict[str, Any]) -> list[AgentProfile]:
    """Build the legacy-compatible primary and the three starter personalities."""
    base = {
        "model": settings.get("model"),
        "reasoning_effort": settings.get("reasoning_effort", DEFAULT_REASONING_EFFORT),
        "reasoning_summary": settings.get("reasoning_summary", DEFAULT_REASONING_SUMMARY),
        "text_verbosity": settings.get("text_verbosity", DEFAULT_TEXT_VERBOSITY),
        "web_search": bool(settings.get("web_search", False)),
    }
    profiles = [
        AgentProfile(
            agent_id=PRIMARY_AGENT_ID,
            name="Codex Assist",
            prompt=settings.get("prompt", DEFAULT_PROMPT),
            **base,
        )
    ]
    profiles.extend(
        AgentProfile(agent_id=agent_id, name=name, prompt=prompt, **base)
        for agent_id, name, prompt in PERSONALITIES
    )
    return profiles


def get_agent_profiles(entry: ConfigEntry) -> list[AgentProfile]:
    """Load saved profiles, or present compatible defaults for an older entry."""
    settings = {**entry.data, **entry.options}
    saved_profiles = entry.options.get(CONF_AGENTS)
    if not isinstance(saved_profiles, list):
        return default_agent_profiles(settings)

    profiles: list[AgentProfile] = []
    for item in saved_profiles:
        if not isinstance(item, dict):
            continue
        agent_id = item.get("id")
        name = item.get("name")
        prompt = item.get("prompt")
        if not all(isinstance(value, str) and value.strip() for value in (agent_id, name, prompt)):
            continue
        profiles.append(
            AgentProfile(
                agent_id=agent_id,
                name=name.strip(),
                prompt=prompt,
                model=item.get("model") if isinstance(item.get("model"), str) else None,
                reasoning_effort=_choice(item.get("reasoning_effort"), "low"),
                reasoning_summary=_choice(item.get("reasoning_summary"), "auto"),
                text_verbosity=_choice(item.get("text_verbosity"), "medium"),
                web_search=bool(item.get("web_search", False)),
            )
        )
    return profiles if profiles else default_agent_profiles(settings)


def _choice(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value else default
