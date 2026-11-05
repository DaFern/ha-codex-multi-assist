"""Allowlisted phone diagnostics; never serialize caller, clip or peer data."""

import logging

LOGGER = logging.getLogger(__name__)
STAGES = {"stt", "handoff", "agent", "flow", "connection"}
RESULTS = {
    "binding",
    "account_or_metadata",
    "reserve",
    "source",
    "source_metadata",
    "capture",
    "audio_limit",
    "audio_format",
    "transcription",
    "handoff",
    "ready",
    "cancelled",
    "failed",
    "missing",
    "binding_mismatch",
    "expired",
    "consumed",
    "discarded",
    "disconnect",
    "received",
    "notice_new",
    "notice_repeat",
    "stop_no_session",
    "stop_paused",
    "stop_unverified",
    "stale_turn",
    "closing",
    "prepare",
    "cancel_before_start",
    "cancel_discarded",
    "cancel_unverified",
    "control_guard_paused",
    "resume_notice",
    "resume_started",
}
CONTROLS = {
    "none",
    "start_learning",
    "continue_learning",
    "stop",
    "cancel",
    "uncertain_control",
    "status",
    "privacy",
    "start_learning_punctuation",
    "continue_learning_punctuation",
    "notice_like",
    "other",
}
CONTINUITY = {
    "none",
    "new_scope",
    "same_scope",
    "expired_scope",
    "chat_changed",
    "connection_changed",
    "account_changed",
}
PHASES = {"none", "consent", "resume_consent", "paused", "sample", "processing", "attention"}


def _allowed(value, choices):
    # Reject arbitrary objects as well as strings not in the fixed vocabulary.
    return value if type(value) is str and value in choices else "unknown"


def record(stage, result, *, control="none", continuity="none", phase="none", audio_bytes=0):
    """Only fixed enums and bounded PCM duration may enter the log record."""
    audio_ms = min(max(audio_bytes, 0), 320000) // 32 if type(audio_bytes) is int else 0
    LOGGER.info(
        "Phone learning diagnostic: stage=%s result=%s control=%s "
        "continuity=%s phase=%s audio_ms=%d",
        _allowed(stage, STAGES),
        _allowed(result, RESULTS),
        _allowed(control, CONTROLS),
        _allowed(continuity, CONTINUITY),
        _allowed(phase, PHASES),
        audio_ms,
    )
