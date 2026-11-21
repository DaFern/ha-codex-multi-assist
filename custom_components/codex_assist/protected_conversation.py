"""Volatile microphone window only; durable dialogue is separate from authority."""

import time

LISTEN_SECONDS = 8
STOP_PHRASES = frozenset({
    "that's all", "thats all", "that is all", "stop listening",
    "end conversation", "goodbye",
})


def is_stop_phrase(text):
    return " ".join(text.casefold().replace("’", "'").strip().rstrip(".!?").split()) in STOP_PHRASES


def is_forget_phrase(text):
    return " ".join(text.casefold().strip().rstrip(".!?").split()) in {
        "forget this conversation", "clear this conversation", "start a new conversation",
    }


class ProtectedConversation:
    """One satellite/connection's microphone state, never dialogue or permissions."""

    def __init__(self):
        self.timer = None
        self.clear()

    def cancel_timer(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None

    def clear(self):
        self.cancel_timer()
        self.deadline = None
        self.pending_speech = False
        self.speech_started = False

    def reply_ready(self):
        """Queue a listening window, without starting it before playback finishes."""
        self.clear()
        self.pending_speech = True

    def open_window(self):
        """Called after native TTS playback finishes, not when synthesis starts."""
        if not self.pending_speech:
            return False
        self.pending_speech = False
        self.deadline = time.monotonic() + LISTEN_SECONDS
        self.speech_started = False
        return True

    def note_speech(self):
        """Activity extends this utterance only; it grants no identity or authority."""
        if self.deadline is not None and time.monotonic() <= self.deadline:
            self.speech_started = True
            self.deadline = None
            self.cancel_timer()


class SpeechActivity:
    """Use HA's existing microVAD library on 16kHz, 16-bit mono PCM frames."""

    def __init__(self):
        from pymicro_vad import MicroVad

        self.vad = MicroVad()
        self.buffer = bytearray()
        self.frames = 0

    def process(self, audio):
        self.buffer.extend(audio)
        detected = False
        while len(self.buffer) >= 320:  # native microVAD expects 10ms
            chunk = bytes(self.buffer[:320])
            del self.buffer[:320]
            probability = self.vad.Process10ms(chunk)
            self.frames = self.frames + 1 if probability >= 0.5 else 0
            detected |= self.frames >= 3
        return detected
