"""Data-only continuity and listening-window state; no device or network access."""

import time
from unittest.mock import Mock

import pytest

from custom_components.codex_assist.protected_conversation import (
    LISTEN_SECONDS,
    ProtectedConversation,
    SpeechActivity,
    is_stop_phrase,
    stop_phrase_reply,
)


def test_window_starts_after_playback_not_after_reply_preparation():
    state = ProtectedConversation()
    state.reply_ready()
    assert state.pending_speech and state.deadline is None
    before = time.monotonic()
    assert state.open_window()
    assert LISTEN_SECONDS == 8
    assert before + 8 <= state.deadline <= time.monotonic() + 8
    assert not state.open_window()  # duplicate playback callback cannot extend it


def test_speech_within_window_cancels_idle_timer_but_late_audio_cannot_extend():
    state = ProtectedConversation()
    state.reply_ready()
    state.open_window()
    timer = state.timer = Mock()
    state.note_speech()
    timer.cancel.assert_called_once()
    assert state.speech_started and state.deadline is None
    state.speech_started = False
    state.deadline = time.monotonic() - 1
    state.note_speech()
    assert not state.speech_started


def test_clear_discards_only_microphone_state_and_timer():
    state = ProtectedConversation()
    state.reply_ready()
    timer = state.timer = Mock()
    state.clear()
    timer.cancel.assert_called_once()
    assert not state.pending_speech
    assert not hasattr(state, "history") and not hasattr(state, "candidates")


@pytest.mark.parametrize("phrase", [
    "That's all.", "that’s all", "STOP LISTENING", "goodbye!",
    "thanks", "Thanks.", " THANKS! ", "thank you", "Thank you!", "thank   you",
])
def test_explicit_stop_phrases(phrase):
    assert is_stop_phrase(phrase)


@pytest.mark.parametrize("phrase", ["Thanks.", " THANKS! ", "Thank you", "thank   you!?"])
def test_thanks_get_a_spoken_acknowledgement(phrase):
    assert stop_phrase_reply(phrase) == "You're welcome."


@pytest.mark.parametrize("phrase", ["That's all.", "STOP LISTENING", "goodbye!"])
def test_other_stop_phrases_keep_the_existing_reply(phrase):
    assert stop_phrase_reply(phrase) == "Okay."


def test_music_stop_or_a_quoted_phrase_is_not_a_conversation_stop():
    assert not is_stop_phrase("stop the music")
    assert not is_stop_phrase("play the song That's All")


@pytest.mark.parametrize("phrase", [
    "Thanks, turn off the light", "Thank you, set a pasta timer",
    "No thanks", "Thanks for turning on the light", "play the song Thank You",
    'say "thanks"', "what does thank you mean?",
])
def test_politeness_inside_a_larger_request_is_not_a_conversation_stop(phrase):
    assert not is_stop_phrase(phrase)


def test_microvad_observer_handles_partial_native_frames_without_authorising_anything():
    activity = SpeechActivity.__new__(SpeechActivity)
    activity.buffer = bytearray()
    activity.frames = 0
    activity.vad = Mock()
    activity.vad.Process10ms.return_value = 0.9
    assert not activity.process(b"\0" * 319)
    assert not activity.process(b"\0" * 321)
    assert activity.process(b"\0" * 320)
    assert len(activity.buffer) == 0
