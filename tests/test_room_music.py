"""Bounded room routing data has no permission semantics or runtime dependency."""

import pytest

from custom_components.codex_assist.room_music import room_music_defaults


@pytest.mark.parametrize("value", [
    [], "not a map", {"room": None}, {"room": ["media_player.test"]},
    {"room": "switch.test"}, {"": "media_player.test"}, {True: "media_player.test"},
    {"r" * 129: "media_player.test"},
    {f"room_{i}": "media_player.test" for i in range(65)},
])
def test_malformed_preferences_fail_closed(value):
    assert room_music_defaults(value) is None


def test_room_preferences_are_copied_and_none_is_unconfigured():
    original = {"room": "media_player.test"}
    copied = room_music_defaults(original)
    original["room"] = "media_player.other"
    assert copied == {"room": "media_player.test"}
    assert room_music_defaults(None) == room_music_defaults({}) == {}
