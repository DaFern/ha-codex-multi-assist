"""Read-only dependency review. Never disable, delete or rewrite a user's entity."""

from homeassistant.components import stt
from homeassistant.helpers import entity_registry as er

from .learning.const import CONF_CONTROL_STT
from .voice_match import (
    CONF_CLEAN_TRANSCRIPT,
    CONF_PERSONAL_STT_SOURCE,
    CONF_VOICE_MATCH_HOST,
)


def cleanup_report(hass, entry):
    """Limit suggestions to this configured backend and report known references."""
    host = entry.options.get(CONF_VOICE_MATCH_HOST)
    if not host or not entry.options.get(CONF_CLEAN_TRANSCRIPT):
        return "Save the direct Voice Match connection first. Existing sources are still needed."
    if "stt" not in hass.config.components:
        return "Source dependencies are unavailable. Leave existing sources enabled."
    from homeassistant.components import assist_pipeline

    try:
        pipelines = assist_pipeline.async_get_pipelines(hass)
    except KeyError:
        return "Assistant dependencies are unavailable. Leave existing sources enabled."
    registry = er.async_get(hass)
    lines = []
    for item in registry.entities.values():
        if item.domain != "stt" or item.platform != "wyoming" or item.disabled_by is not None:
            continue
        source_entry = hass.config_entries.async_get_entry(item.config_entry_id)
        source = stt.async_get_speech_to_text_entity(hass, item.entity_id)
        info = getattr(getattr(getattr(source, "service", None), "info", None), "asr", [])
        if (source_entry is None or source_entry.data.get("host") != host or not info
                or info[0].name not in {"voice-match", "voice-match-personal"}):
            continue
        used = any(pipeline.stt_engine == item.entity_id for pipeline in pipelines)
        for other in hass.config_entries.async_entries():
            # Check legacy wrappers and the ordinary-Whisper learning dependency.
            if (other.options.get(CONF_CONTROL_STT) == item.entity_id
                    or (CONF_VOICE_MATCH_HOST not in other.options
                        and other.options.get(CONF_PERSONAL_STT_SOURCE) == item.entity_id)):
                used = True
        status = ("Still referenced; keep enabled" if used else
                  "No known assistant/source references; review other uses before disabling")
        lines.append(f"- `{item.entity_id}`: {status}.")
    return "\n".join(lines) or "No loaded legacy Voice Match STT sources found for this host."
