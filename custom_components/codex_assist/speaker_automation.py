"""Private, request-bound dispatch to explicitly configured HA voice triggers.

No service-call bridge, account impersonation, public event or last-speaker state.
The condition accepts only the exact metadata object of a currently running
trigger callback. Copying trace fields or supplying a voice name is insufficient.
"""

from collections.abc import Mapping
from dataclasses import dataclass

DATA_SPEAKER_AUTOMATIONS = "codex_assist_speaker_automations"


def normalize_sentence(text):
    """Match literal phrases, tolerating case, whitespace and final punctuation."""
    return " ".join(text.casefold().split()).rstrip(".!?。！？")


@dataclass(frozen=True)
class DispatchResult:
    matched: bool = False
    response: str | None = None


class SpeakerAutomations:
    """HA-instance-local subscriptions and active automation-run metadata."""

    max_active = 256

    def __init__(self):
        self.listeners = {}
        self.active = {}

    def subscribe(self, sentences, callback):
        token = object()
        self.listeners[token] = (frozenset(normalize_sentence(s) for s in sentences), callback)

        def remove():
            self.listeners.pop(token, None)

        return remove

    def speaker_is(self, variables, voice):
        if not isinstance(variables, Mapping):
            return False
        trigger = variables.get("trigger")
        if not isinstance(trigger, Mapping):
            return False
        metadata = trigger.get("voice_match")
        record = self.active.get(id(metadata))
        return bool(record is not None and record[0] is metadata
                    and voice is not None and record[1] == voice)

    async def dispatch(self, request, user_input=None):
        """Run matching automations once; never retry actions through the model."""
        if not request.verified:
            return DispatchResult()
        sentence = normalize_sentence(request.text)
        matches = [(token, cb) for token, (phrases, cb) in self.listeners.items()
                   if sentence in phrases]
        if not matches:
            return DispatchResult()
        response = None
        for token, callback in matches:
            if token not in self.listeners:
                continue
            if len(self.active) >= self.max_active:
                raise RuntimeError("Too many active speaker automations")
            metadata = {"voice": request.voice, "sentence": request.text}
            self.active[id(metadata)] = (metadata, request.voice)
            try:
                # HA input is supplied out-of-band, never from model arguments.
                if user_input is None:
                    result = await callback(metadata)
                else:
                    result = await callback(metadata, user_input)
                if response is None and isinstance(result, str) and result.strip():
                    response = result
            finally:
                self.active.pop(id(metadata), None)
        return DispatchResult(True, response)


def automations_for_hass(hass):
    """No speaker profile or request data is persisted."""
    if DATA_SPEAKER_AUTOMATIONS not in hass.data:
        hass.data[DATA_SPEAKER_AUTOMATIONS] = SpeakerAutomations()
    return hass.data[DATA_SPEAKER_AUTOMATIONS]
