"""Automation editor condition for the speaker on this voice-triggered run."""

import re

import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.condition import Condition

from .speaker_automation import automations_for_hass

schema = getattr(cv, "probatio", vol)
_SCHEMA = schema.Schema({schema.Required("options"): {
    schema.Required("voice"): schema.All(
        str, schema.Match(re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$"))
    ),
}})


class SpeakerIsCondition(Condition):
    """A profile hint, not an authenticated HA user or authorisation check."""

    @classmethod
    async def async_validate_config(cls, hass, config):
        return _SCHEMA(config)

    def __init__(self, hass, config):
        super().__init__(hass, config)
        self._voice = config.options["voice"]

    @property
    def needs_polling(self):
        return False

    def _async_check(self, variables=None, **kwargs):
        return automations_for_hass(self._hass).speaker_is(variables, self._voice)


async def async_get_conditions(hass):
    return {"speaker_is": SpeakerIsCondition}
