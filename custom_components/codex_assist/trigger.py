"""Literal sentence triggers after the paired Voice Match packet is verified."""

import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.script import ScriptRunResult
from homeassistant.helpers.trigger import Trigger
from homeassistant.helpers.typing import UNDEFINED

from .speaker_automation import automations_for_hass, normalize_sentence

schema = getattr(cv, "probatio", vol)


def _sentences(value):
    if isinstance(value, str):
        value = [value]
    if (not isinstance(value, list) or not 1 <= len(value) <= 32
            or any(not isinstance(s, str) or not 1 <= len(s) <= 256
                   or not normalize_sentence(s) for s in value)):
        raise schema.Invalid("Provide 1 to 32 non-empty literal sentences")
    return value


_SCHEMA = schema.Schema({schema.Required("options"): {schema.Required("sentence"): _sentences}})


class VoiceSentenceTrigger(Trigger):
    """Opt-in voice automation; no model-selected speaker or service target."""

    @classmethod
    async def async_validate_config(cls, hass, config):
        return _SCHEMA(config)

    def __init__(self, hass, config):
        super().__init__(hass, config)
        self._sentences = config.options["sentence"]

    async def async_attach_runner(self, run_action, report_not_triggered=None):
        async def call_action(metadata, user_input):
            result = await run_action(
                {"sentence": user_input.text, "voice_match": metadata,
                 "device_id": user_input.device_id,
                 "satellite_id": getattr(user_input, "satellite_id", None)},
                "Voice Match sentence", user_input.context,
            )
            if (isinstance(result, ScriptRunResult)
                    and result.conversation_response not in (None, UNDEFINED)):
                return result.conversation_response
            return None

        return automations_for_hass(self._hass).subscribe(self._sentences, call_action)


async def async_get_triggers(hass):
    return {"voice_sentence": VoiceSentenceTrigger}
