"""Configuration-entry module boundaries, independent of provider credentials."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import Platform

CONF_MODULE = "module"


def learning_supported() -> bool:
    """Keep the existing companion's HA floor without raising Codex's floor."""
    from homeassistant.const import MAJOR_VERSION, MINOR_VERSION

    return (MAJOR_VERSION, MINOR_VERSION) >= (2026, 10)


class EntryModule(StrEnum):
    """Independently configured modules within the single integration domain."""

    CODEX = "codex"
    VOICE_MATCH = "voice_match"


def entry_module(entry: ConfigEntry) -> EntryModule:
    """Existing Codex entries need no stored-data rewrite or entity-ID change."""
    return EntryModule(entry.data.get(CONF_MODULE, EntryModule.CODEX))


@dataclass(frozen=True)
class ModuleRuntime:
    """Loaded platforms belong only to this entry, never another module."""

    module: EntryModule
    platforms: tuple[Platform, ...]


if TYPE_CHECKING:
    type ModuleConfigEntry = ConfigEntry[ModuleRuntime]
