"""General direction-conflict vetoes; these tests do not simulate model intelligence."""

import pytest

from custom_components.codex_assist.protected_interpretation import (
    explicit_direction_conflict,
    resolve_reference,
)


@pytest.mark.parametrize(("text", "name", "args"), [
    ("Turn the lounge lamps off", "guest_on_off", {"operation": "turn_on"}),
    ("No, off!", "guest_on_off", {"operation": "turn_on"}),
    ("Off please", "guest_on_off", {"operation": "turn_on"}),
    ("Switch the fan on", "guest_on_off", {"operation": "turn_off"}),
    ("Pause it", "guest_music", {"action": "resume"}),
    ("Resume please", "guest_music", {"action": "pause"}),
    ("Make it quieter", "guest_music", {"action": "volume_up"}),
    ("Turn it up", "guest_music", {"action": "volume_down"}),
    ("The previous song", "guest_music", {"action": "next"}),
    ("Next track", "guest_music", {"action": "previous"}),
])
def test_explicit_latest_direction_vetoes_an_opposite_proposal(text, name, args):
    assert explicit_direction_conflict(text, "codex_assist__" + name, args)


@pytest.mark.parametrize("text", [
    "They are already on", "Why are they on?", "Don't turn it off",
    "Turn one on and the other off", "I said not on, off", "The lights",
    "Turn the lamps of", "The other one",
])
def test_ambiguous_negated_or_near_miss_wording_is_not_rewritten_by_a_keyword_parser(text):
    assert explicit_direction_conflict(
        text, "codex_assist__guest_on_off", {"operation": "turn_off"},
    ) is None


def test_unknown_security_or_other_tool_is_never_granted_by_interpretation():
    assert explicit_direction_conflict("Open it", "unlock", {"entity_id": "lock.test"}) is None


def test_alias_resolution_is_unique_exact_and_domain_scoped():
    catalogue = [
        {"entity_id": "light.desk", "name": "Desk", "aliases": ["Reading lamp"]},
        {"entity_id": "fan.desk", "name": "Desk", "aliases": ["Breeze"]},
    ]
    assert resolve_reference("READING LAMP", catalogue, {"light"}) == "light.desk"
    assert resolve_reference("Desk", catalogue, {"light", "fan"}) is None
    assert resolve_reference("Readin lamp", catalogue, {"light"}) is None
    assert resolve_reference("Breeze", catalogue, {"light"}) is None
    assert resolve_reference("light.desk", catalogue, {"light"}) == "light.desk"
