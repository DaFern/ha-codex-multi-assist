"""Request-scoped, entity-limited native Assist access for neutral satellite turns."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import intent, llm

from . import DOMAIN
from .satellite_constants import CONF_NEUTRAL_ENTITY_IDS as CONF_NEUTRAL_ENTITY_IDS
from .satellite_constants import (
    MAX_NEUTRAL_ENTITIES,
    NEUTRAL_API_ID,
)
from .satellite_runtime import satellite_assist_context as satellite_assist_context

if TYPE_CHECKING:
    from collections.abc import Iterator

    from homeassistant.core import HomeAssistant

    from .voice_match import PreparedRequest

_BLOCKED_DOMAINS = {"automation", "button", "group", "scene", "script"}
_SAFE_ATTRIBUTES = {
    "current_position",
    "current_temperature",
    "fan_mode",
    "hvac_mode",
    "humidity",
    "percentage",
    "position",
    "preset_mode",
    "temperature",
    "temperature_unit",
}


@dataclass(frozen=True, slots=True)
class NeutralAuthorization:
    """Authority bound to one verified neutral turn and its original HA Context."""

    context: Any
    prepared_request: PreparedRequest
    satellite_id: str
    entity_ids: tuple[str, ...]


_NEUTRAL_AUTHORIZATION: ContextVar[NeutralAuthorization | None] = ContextVar(
    "codex_assist_neutral_satellite_authorization", default=None
)
@contextmanager
def neutral_authorization(auth: NeutralAuthorization) -> Iterator[None]:
    """Bind neutral-voice authority only while the API instance is prepared."""
    token = _NEUTRAL_AUTHORIZATION.set(auth)
    try:
        yield
    finally:
        _NEUTRAL_AUTHORIZATION.reset(token)


class AllowedAssistIntentTool(llm.Tool):
    """Run a native entity intent only when its complete target set is allowlisted."""

    def __init__(
        self,
        handler: intent.DynamicServiceIntentHandler,
        authorization: NeutralAuthorization,
    ) -> None:
        native = llm.IntentTool(
            f"{DOMAIN}__neutral__{handler.intent_type}",
            handler,
            integration=DOMAIN,
        )
        self._handler = handler
        self._authorization = authorization
        self.name = native.name
        self.title = native.title
        self.description = native.description
        self.parameters = native.parameters
        self.integration = DOMAIN
        self.annotations = llm.ToolAnnotations(
            read_only=False,
            destructive=True,
            idempotent=False,
            open_world=False,
        )

    async def async_call(self, hass: HomeAssistant, tool_input, llm_context):
        """Execute through the built-in intent handler with exact matched states."""
        auth = self._authorization
        if (
            auth is None
            or llm_context.context is not auth.context
            or llm_context.assistant != "conversation"
            or not auth.prepared_request.verified
            or auth.prepared_request.voice is not None
            or auth.prepared_request.ha_user_id is not None
        ):
            return llm.ToolResult(data={"error": "Satellite control is not authorized."},
                                  error=True)

        satellite = er.async_get(hass).async_get(auth.satellite_id)
        if satellite is None or satellite.domain != "assist_satellite":
            return llm.ToolResult(data={"error": "Satellite control is not authorized."},
                                  error=True)

        try:
            args = self.parameters(tool_input.tool_args)
            slots = {
                key: {"value": value}
                for key, value in args.items()
                if not intent.is_blank_slot_value(value)
            }
            slots = self._handler.async_validate_slots(slots)
            constraints = self._constraints(slots)
            if not constraints.has_constraints:
                return self._denied()

            preferences = llm.async_get_match_preferences(hass, llm_context)
            states = hass.states.async_all()
            if not states:
                return self._denied()
            match = intent.async_match_targets(
                hass,
                constraints,
                preferences,
                states=states,
            )
            if not match.is_match or not match.states:
                return self._denied()

            allowed = self._currently_allowed_states(hass, auth)
            matched_ids = {state.entity_id for state in match.states}
            if (
                not matched_ids.issubset(allowed)
                or any(state.domain in _BLOCKED_DOMAINS for state in match.states)
            ):
                return self._denied()

            intent_obj = intent.Intent(
                hass,
                platform=llm_context.platform,
                intent_type=self._handler.intent_type,
                slots=slots,
                text_input=None,
                context=auth.context,
                language=llm_context.language or hass.config.language,
                assistant="conversation",
                device_id=llm_context.device_id,
                satellite_id=auth.satellite_id,
                conversation_agent_id=getattr(llm_context, "agent_id", None),
            )
            result = await self._handler.async_handle_states(
                intent_obj,
                match,
                constraints,
                preferences,
            )
        except Exception:
            return llm.ToolResult(
                data={"error": "Home Assistant could not complete that allowed action."},
                error=True,
            )
        return llm.ToolResult(data=llm.IntentResponseDict(result))

    def _constraints(self, slots: dict[str, Any]) -> intent.MatchTargetsConstraints:
        """Build the same native target constraints used by service intents."""
        name = slots.get("name", {}).get("value")
        if name == "all":
            name = None
        domain_slot = slots.get("domain", {}).get("value")
        domains = (
            set(domain_slot)
            if domain_slot
            else self._handler.required_domains
        )
        device_class_slot = slots.get("device_class", {}).get("value")
        device_classes = set(device_class_slot) if device_class_slot else None
        return intent.MatchTargetsConstraints(
            name=name,
            area_name=slots.get("area", {}).get("value"),
            floor_name=slots.get("floor", {}).get("value"),
            domains=domains,
            device_classes=device_classes,
            features=self._handler.required_features,
            states=self._handler.required_states,
            assistant="conversation",
        )

    @staticmethod
    def _currently_allowed_states(hass, auth: NeutralAuthorization) -> set[str]:
        """Recheck selection, registry, Assist exposure, availability and domain."""
        registry = er.async_get(hass)
        allowed = set(auth.entity_ids)
        return {
            entity_id
            for entity_id in allowed
            if registry.async_get(entity_id) is not None
            and entity_id.partition(".")[0] not in _BLOCKED_DOMAINS
            and async_should_expose(hass, "conversation", entity_id)
            and (state := hass.states.get(entity_id)) is not None
            and state.state not in {"unknown", "unavailable"}
        }

    @staticmethod
    def _denied():
        return llm.ToolResult(
            data={"error": "No unique available target is allowed for that request."},
            error=True,
        )


class AllowedEntityContextTool(llm.Tool):
    """Read only current states of selected, Assist-exposed entities."""

    name = f"{DOMAIN}__neutral__GetLiveContext"
    title = "Get allowed live context"
    integration = DOMAIN
    description = (
        "Read current state for entities selected in the neutral satellite allowlist. "
        "Filter by name, domain, or area when useful."
    )
    annotations = llm.ToolAnnotations(
        read_only=True,
        destructive=False,
        idempotent=True,
        open_world=False,
    )
    parameters = probatio.Schema({
        probatio.Optional("name"): str,
        probatio.Optional("domain"): probatio.Any(str, [str]),
        probatio.Optional("area"): str,
    })

    def __init__(self, authorization: NeutralAuthorization) -> None:
        """Bind authority to this API-instance tool, not its caller's context."""
        self._authorization = authorization

    async def async_call(self, hass: HomeAssistant, tool_input, llm_context):
        auth = self._authorization
        if (
            auth is None
            or llm_context.context is not auth.context
            or llm_context.assistant != "conversation"
            or not auth.prepared_request.verified
            or auth.prepared_request.voice is not None
            or auth.prepared_request.ha_user_id is not None
        ):
            return llm.ToolResult(data={"error": "Satellite context is not authorized."},
                                  error=True)
        try:
            args = self.parameters(tool_input.tool_args)
            domains = args.get("domain")
            if isinstance(domains, str):
                domains = [domains]
            constraints = intent.MatchTargetsConstraints(
                name=args.get("name"),
                area_name=args.get("area"),
                domains=domains,
                assistant="conversation",
                allow_duplicate_names=True,
            )
            allowed = AllowedAssistIntentTool._currently_allowed_states(hass, auth)
            candidates = [
                state for state in hass.states.async_all()
                if state.entity_id in allowed
            ]
            if not candidates:
                return llm.ToolResult(data={"entities": []})
            if constraints.has_constraints:
                matched = intent.async_match_targets(
                    hass, constraints, states=candidates
                )
                if not matched.is_match:
                    return llm.ToolResult(data={"entities": []})
                candidates = matched.states
            entities = [
                {
                    "entity_id": state.entity_id,
                    "name": state.attributes.get("friendly_name", state.entity_id),
                    "domain": state.domain,
                    "state": state.state,
                    "attributes": {
                        key: state.attributes[key]
                        for key in _SAFE_ATTRIBUTES
                        if key in state.attributes
                        and isinstance(state.attributes[key], (str, int, float, bool))
                    },
                }
                for state in candidates[:40]
            ]
        except Exception:
            return llm.ToolResult(data={"error": "Allowed entity state is unavailable."},
                                  error=True)
        return llm.ToolResult(data={"entities": entities})


class NeutralSatelliteAPI(llm.API):
    """Expose only selected, standard entity-intent actions for neutral turns."""

    async def async_get_api_instance(self, llm_context: llm.LLMContext) -> llm.APIInstance:
        auth = _NEUTRAL_AUTHORIZATION.get()
        tools = []
        if (
            auth is not None
            and auth.context is llm_context.context
            and llm_context.assistant == "conversation"
            and auth.prepared_request.verified
            and auth.prepared_request.voice is None
            and auth.prepared_request.ha_user_id is None
            and len(auth.entity_ids) <= MAX_NEUTRAL_ENTITIES
        ):
            allowed = AllowedAssistIntentTool._currently_allowed_states(self.hass, auth)
            allowed_domains = {
                entity_id.partition(".")[0] for entity_id in allowed
            }
            if allowed:
                tools.append(AllowedEntityContextTool(auth))
                for handler in intent.async_get(self.hass):
                    if not isinstance(handler, intent.DynamicServiceIntentHandler):
                        continue
                    if (
                        handler.required_domains
                        and not handler.required_domains.intersection(allowed_domains)
                    ):
                        continue
                    tools.append(AllowedAssistIntentTool(handler, auth))

        prompt = (
            "This is a verified Voice Match turn with no confident profile match. "
            "You may control only the available entities selected in the neutral "
            "satellite allowlist, using the supplied standard Home Assistant entity "
            "intent tools. Never claim broader access. Do not invoke scripts, "
            "automations, scenes, buttons, MCP tools, or arbitrary services. If a "
            "request cannot be completed with an allowed intent, explain that."
        )
        if tools and auth is not None:
            entries = []
            for entity_id in sorted(
                AllowedAssistIntentTool._currently_allowed_states(self.hass, auth)
            ):
                state = self.hass.states.get(entity_id)
                if state is not None:
                    entries.append(
                        f"- {state.attributes.get('friendly_name', entity_id)} "
                        f"({entity_id}; {state.domain}; {state.state})"
                    )
            prompt += "\n\nSelected available entities:\n" + "\n".join(entries[:40])
        return llm.APIInstance(
            api=self,
            api_prompt=prompt,
            llm_context=llm_context,
            tools=tools,
        )


def async_register_neutral_satellite_api(hass: HomeAssistant):
    """Register the request-scoped neutral-voice entity allowlist API."""
    return llm.async_register_api(
        hass,
        NeutralSatelliteAPI(
            hass=hass,
            id=NEUTRAL_API_ID,
            name="Codex Assist Neutral Satellite",
        ),
    )
