"""Request-bound, permission-checked Music Assistant controls."""

from __future__ import annotations

import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm

from .satellite_constants import CONF_MUSIC_PLAYER_IDS as CONF_MUSIC_PLAYER_IDS
from .satellite_constants import MAX_PLAYERS as MAX_PLAYERS
from .satellite_constants import MUSIC_API_ID as MUSIC_API_ID

if TYPE_CHECKING:
    from homeassistant.core import Context, HomeAssistant

    from .voice_match import PreparedRequest


MAX_SEARCH_ITEMS = 10

_MUSIC_AUTH: ContextVar[MusicAuthorization | None] = ContextVar(
    "codex_assist_music_authorization", default=None
)


@dataclass(slots=True)
class MusicAuthorization:
    """Immutable request identity plus bounded, request-local search choices."""

    context: Context
    prepared_request: PreparedRequest
    user_id: str
    player_ids: tuple[str, ...]
    satellite_id: str | None
    device_id: str | None
    candidates: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)


@contextmanager
def music_authorization(auth: MusicAuthorization):
    """Bind verified voice authority only while this request is being handled."""
    token = _MUSIC_AUTH.set(auth)
    try:
        yield
    finally:
        _MUSIC_AUTH.reset(token)


def current_music_authorization() -> MusicAuthorization | None:
    """Return the current request's authorization, if any."""
    return _MUSIC_AUTH.get()


def _bounded_text(value: Any, limit: int = 256) -> str:
    return value[:limit] if isinstance(value, str) and value.isprintable() else ""


def _normalized(value: str) -> str:
    return " ".join("".join(char.casefold() if char.isalnum() else " " for char in value).split())


class MusicControlTool(llm.Tool):
    """One fixed Music Assistant capability; arbitrary services are impossible."""

    name = "codex_assist__music_control"
    title = "Control Music Assistant"
    integration = "codex_assist"
    description = (
        "Search and play music, control playback and volume, or read and clear the queue "
        "on an authorized Music Assistant speaker. Name a room or speaker when needed."
    )
    annotations = llm.ToolAnnotations(
        read_only=False, destructive=True, idempotent=False, open_world=False
    )
    parameters = probatio.Schema({
        probatio.Required("action"): probatio.In(
            (
                "play",
                "pause",
                "stop",
                "resume",
                "next",
                "previous",
                "volume",
                "volume_up",
                "volume_down",
                "queue",
                "clear_queue",
                "mute",
                "unmute",
                "seek",
                "shuffle",
                "repeat",
            )
        ),
        probatio.Optional("room"): probatio.All(str, probatio.Length(min=1, max=128)),
        probatio.Optional("speaker"): probatio.All(str, probatio.Length(min=1, max=128)),
        probatio.Optional("query"): probatio.All(str, probatio.Length(min=1, max=256)),
        probatio.Optional("kind"): probatio.In(
            ("track", "album", "artist", "playlist", "radio", "podcast", "audiobook")
        ),
        probatio.Optional("candidate_id"): probatio.All(
            str, probatio.Length(min=1, max=64)
        ),
        probatio.Optional("mode"): probatio.In(("replace", "next", "add", "radio")),
        probatio.Optional("level"): probatio.All(
            int, probatio.Range(min=0, max=100)
        ),
        probatio.Optional("position"): probatio.All(
            probatio.Coerce(float), probatio.Range(min=0, max=86400),
        ),
        probatio.Optional("enabled"): bool,
        probatio.Optional("repeat_mode"): probatio.In(("off", "one", "all")),
    })

    def __init__(self, authorization: MusicAuthorization) -> None:
        self._authorization = authorization

    async def async_call(self, hass: HomeAssistant, tool_input, llm_context):
        auth = self._authorization
        if not self._request_identity_valid(llm_context):
            return llm.ToolResult(data={"error": "Music control is not authorized."}, error=True)
        args = self.parameters(tool_input.tool_args)
        target_id, problem = self._resolve_target(hass, auth, args)
        if target_id is None:
            return llm.ToolResult(
                data={"response_type": "query_answer", "status": "clarify", "message": problem}
            )
        if problem := await self._target_problem(hass, auth, target_id):
            return problem
        action = args["action"]
        try:
            if action == "play":
                if candidate_id := args.get("candidate_id"):
                    return await self._play_candidate(hass, auth, target_id, candidate_id, args)
                if not (query := args.get("query")):
                    return llm.ToolResult(
                        data={"response_type": "query_answer", "status": "clarify",
                              "message": "What would you like to play?"}
                    )
                return await self._search(hass, auth, target_id, query, args.get("kind"))
            if action == "queue":
                if not await self._assert_allowed(hass, auth, target_id):
                    raise PermissionError
                response = await hass.services.async_call(
                    "music_assistant",
                    "get_queue",
                    {"entity_id": target_id},
                    blocking=True,
                    return_response=True,
                    context=auth.context,
                )
                return llm.ToolResult(data=self._queue_result(response, target_id))
            if action == "clear_queue":
                return await self._call_player(hass, auth, target_id, "clear_playlist", {})
            service = {
                "pause": "media_pause",
                "stop": "media_stop",
                "resume": "media_play",
                "next": "media_next_track",
                "previous": "media_previous_track",
                "volume_up": "volume_up",
                "volume_down": "volume_down",
                "volume": "volume_set",
                "mute": "volume_mute",
                "unmute": "volume_mute",
                "seek": "media_seek",
                "shuffle": "shuffle_set",
                "repeat": "repeat_set",
            }[action]
            data = (
                {"volume_level": args["level"] / 100}
                if action == "volume" and "level" in args
                else {}
            )
            if action == "volume" and "level" not in args:
                return llm.ToolResult(
                    data={"response_type": "query_answer", "status": "clarify",
                          "message": "What volume level from 0 to 100?"}
                )
            if action in {"mute", "unmute"}:
                data = {"is_volume_muted": action == "mute"}
            elif action == "seek":
                if "position" not in args:
                    return llm.ToolResult(data={
                        "response_type": "query_answer", "status": "clarify",
                        "message": "Which playback position in seconds?",
                    })
                data = {"seek_position": args["position"]}
            elif action == "shuffle":
                if "enabled" not in args:
                    return llm.ToolResult(data={
                        "response_type": "query_answer", "status": "clarify",
                        "message": "Should shuffle be on or off?",
                    })
                data = {"shuffle": args["enabled"]}
            elif action == "repeat":
                if "repeat_mode" not in args:
                    return llm.ToolResult(data={
                        "response_type": "query_answer", "status": "clarify",
                        "message": "Repeat this track, all tracks, or off?",
                    })
                data = {"repeat": args["repeat_mode"]}
            return await self._call_player(hass, auth, target_id, service, data)
        except Exception:
            return llm.ToolResult(
                data={"error": "Music Assistant could not complete that request."}, error=True
            )

    def _request_identity_valid(self, llm_context):
        """Recognised-user contract; guest subclasses supply separate authority."""
        auth = self._authorization
        return (
            llm_context.context is auth.context
            and auth.prepared_request.verified
            and bool(auth.prepared_request.voice)
            and auth.prepared_request.ha_user_id == auth.user_id
        )

    async def _target_problem(self, hass, auth, target_id):
        user = await hass.auth.async_get_user(auth.user_id)
        if not user or not user.is_active or user.system_generated:
            return llm.ToolResult(data={"error": "Music control is not authorized."}, error=True)
        if not self._target_is_allowed(hass, user, auth, target_id):
            return llm.ToolResult(
                data={"response_type": "query_answer", "status": "clarify",
                      "message": "Choose an available Music Assistant speaker."}
            )
        return None

    def _resolve_target(self, hass, auth: MusicAuthorization, args: dict[str, Any]):
        """Resolve only exact configured entities, never a similarly named Alexa player."""
        candidates = self._eligible_entities(hass, auth)
        if not candidates:
            return None, "No Music Assistant speakers are configured for this assistant."

        requested_speaker = args.get("speaker")
        requested_room = args.get("room")
        if requested_speaker:
            matches = self._match_speaker(hass, candidates, requested_speaker)
            if len(matches) != 1:
                return None, "Which Music Assistant speaker did you mean?"
            speaker_id = matches[0]
            if requested_room:
                room_target, error = self._match_room(hass, candidates, requested_room)
                if room_target is None:
                    return None, error
                if room_target != speaker_id:
                    return None, "The named speaker and room do not identify the same player."
            return speaker_id, ""

        room = requested_room
        if not room:
            area_id = self._request_area_id(hass, auth)
            if not area_id:
                return None, "Which room or speaker should I use?"
            area = ar.async_get(hass).async_get_area(area_id)
            room = area.name if area else ""
        if not room:
            return None, "Which room or speaker should I use?"
        return self._match_room(hass, candidates, room)

    def _eligible_entities(self, hass, auth: MusicAuthorization) -> tuple[str, ...]:
        if not isinstance(auth.player_ids, tuple) or len(auth.player_ids) > MAX_PLAYERS:
            return ()
        entity_registry = er.async_get(hass)
        return tuple(
            entity_id
            for entity_id in auth.player_ids
            if isinstance(entity_id, str)
            and (entry := entity_registry.async_get(entity_id)) is not None
            and entry.platform == "music_assistant"
            and entity_id.startswith("media_player.")
            and async_should_expose(hass, "conversation", entity_id)
            and (state := hass.states.get(entity_id)) is not None
            and state.state not in {"unknown", "unavailable"}
        )

    def _match_speaker(self, hass, candidates: tuple[str, ...], name: str) -> list[str]:
        wanted = _normalized(name)
        registry = er.async_get(hass)
        matches = []
        for entity_id in candidates:
            entry = registry.async_get(entity_id)
            state = hass.states.get(entity_id)
            names = {entity_id, entity_id.partition(".")[2].replace("_", " ")}
            if state:
                names.add(state.attributes.get("friendly_name", ""))
            if entry:
                names.update(entry.aliases)
                if entry.name:
                    names.add(entry.name)
            if wanted in {_normalized(value) for value in names if isinstance(value, str)}:
                matches.append(entity_id)
        return matches

    def _match_room(self, hass, candidates: tuple[str, ...], name: str):
        areas = ar.async_get(hass)
        wanted = _normalized(name)
        matching_area_ids = []
        for area in areas.async_list_areas():
            aliases = getattr(area, "aliases", ())
            if wanted in {_normalized(value) for value in (area.name, *aliases)}:
                matching_area_ids.append(area.id)
        if len(matching_area_ids) != 1:
            return None, "Which room did you mean?"
        area_id = matching_area_ids[0]
        entity_registry = er.async_get(hass)
        matches = []
        for entity_id in candidates:
            entry = entity_registry.async_get(entity_id)
            if entry and entry.area_id == area_id:
                matches.append(entity_id)
                continue
            if entry and entry.device_id:
                device = dr.async_get(hass).async_get(entry.device_id)
                if device and dr.async_get_effective_area_id(hass, device) == area_id:
                    matches.append(entity_id)
        if len(matches) == 1:
            return matches[0], ""
        active = [eid for eid in matches if hass.states.get(eid).state == "playing"]
        if len(active) == 1:
            return active[0], ""
        if not matches:
            return None, "I don't have a configured Music Assistant speaker in that room."
        return None, "There are multiple configured speakers in that room. Which one?"

    def _request_area_id(self, hass, auth: MusicAuthorization) -> str | None:
        entity_registry = er.async_get(hass)
        if auth.satellite_id:
            entry = entity_registry.async_get(auth.satellite_id)
            if entry and entry.domain == "assist_satellite":
                if entry.area_id:
                    return entry.area_id
                if entry.device_id:
                    device = dr.async_get(hass).async_get(entry.device_id)
                    if device:
                        return dr.async_get_effective_area_id(hass, device)
        if auth.device_id:
            device = dr.async_get(hass).async_get(auth.device_id)
            if device:
                return dr.async_get_effective_area_id(hass, device)
        return None

    def _target_is_allowed(self, hass, user, auth: MusicAuthorization, entity_id: str) -> bool:
        return (
            entity_id in auth.player_ids
            and async_should_expose(hass, "conversation", entity_id)
            and user.permissions.check_entity(entity_id, POLICY_CONTROL)
        )

    async def _search(self, hass, auth, target_id: str, query: str, kind: str | None):
        if not await self._assert_allowed(hass, auth, target_id):
            return llm.ToolResult(data={"error": "Music control is not authorized."}, error=True)
        entity_entry = er.async_get(hass).async_get(target_id)
        if not entity_entry or not entity_entry.config_entry_id:
            return llm.ToolResult(data={"error": "Music Assistant is unavailable."}, error=True)
        data: dict[str, Any] = {
            "config_entry_id": entity_entry.config_entry_id,
            "name": query,
            "limit": MAX_SEARCH_ITEMS,
        }
        if kind:
            data["media_type"] = [kind]
        response = await hass.services.async_call(
            "music_assistant", "search", data, blocking=True, return_response=True,
            context=auth.context,
        )
        if not isinstance(response, dict):
            return llm.ToolResult(
                data={"error": "Music Assistant returned an invalid search result."}, error=True
            )
        rows = []
        for category, category_rows in response.items():
            if not isinstance(category_rows, list):
                continue
            for row in category_rows:
                if isinstance(row, dict):
                    rows.append({**row, "media_type": row.get("media_type", category)})
        rows = rows[:MAX_SEARCH_ITEMS]
        auth.candidates.clear()
        results = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("uri"), str):
                continue
            candidate_id = secrets.token_urlsafe(12)
            auth.candidates[candidate_id] = (target_id, row)
            results.append({
                "candidate_id": candidate_id,
                "title": _bounded_text(row.get("name")),
                "artist": _bounded_text(row.get("artist")),
                "album": _bounded_text(row.get("album")),
                "type": _bounded_text(row.get("media_type")),
            })
        if not results:
            return llm.ToolResult(data={"response_type": "query_answer", "status": "not_found"})
        return llm.ToolResult(
            data={"response_type": "query_answer", "status": "selection_required",
                  "results": results}
        )

    async def _play_candidate(self, hass, auth, target_id: str, candidate_id: str, args):
        candidate = auth.candidates.get(candidate_id)
        if candidate is None or candidate[0] != target_id:
            return llm.ToolResult(
                data={"error": "That music selection is no longer available."}, error=True
            )
        item = candidate[1]
        mode = args.get("mode", "replace")
        enqueue = {"replace": "replace", "next": "next", "add": "add", "radio": "play"}[mode]
        data: dict[str, Any] = {
            "entity_id": target_id,
            "media_id": item["uri"],
            "media_type": item.get("media_type"),
            "enqueue": enqueue,
            "radio_mode": mode == "radio",
        }
        await self._call_service(
            hass, auth, "music_assistant", "play_media", data, target_id=target_id
        )
        auth.candidates.clear()
        return llm.ToolResult(
            data={
                "status": "accepted",
                "operation": "play_media",
                "entity_ids": [target_id],
                "title": _bounded_text(item.get("name")),
                "artist": _bounded_text(item.get("artist")),
            }
        )

    async def _call_player(self, hass, auth, target_id: str, service: str, data: dict[str, Any]):
        await self._call_service(
            hass, auth, "media_player", service, data, target_id=target_id
        )
        return llm.ToolResult(data={
            "status": "accepted", "operation": service, "entity_ids": [target_id],
        })

    async def _call_service(
        self, hass, auth, domain: str, service: str, data: dict[str, Any], *, target_id: str
    ):
        """Recheck the voice account and exposure immediately before fixed service admission."""
        if not await self._assert_allowed(hass, auth, target_id):
            raise PermissionError
        await hass.services.async_call(
            domain,
            service,
            {"entity_id": target_id, **data},
            blocking=True,
            context=auth.context,
        )

    async def _assert_allowed(
        self, hass, auth: MusicAuthorization, target_id: str
    ) -> bool:
        """Recheck account, allowlist, exposure, entity and control permission."""
        user = await hass.auth.async_get_user(auth.user_id)
        if (
            not user
            or not user.is_active
            or user.system_generated
            or target_id not in auth.player_ids
            or not async_should_expose(hass, "conversation", target_id)
            or not user.permissions.check_entity(target_id, POLICY_CONTROL)
        ):
            return False
        state = hass.states.get(target_id)
        entity_entry = er.async_get(hass).async_get(target_id)
        if (
            state is None
            or state.state in {"unknown", "unavailable"}
            or entity_entry is None
            or entity_entry.platform != "music_assistant"
        ):
            return False
        return True

    def _queue_result(self, response: Any, target_id: str) -> dict[str, Any]:
        if not isinstance(response, dict):
            return {"response_type": "query_answer", "status": "unconfirmed"}
        player_queue = response.get(target_id)
        if not isinstance(player_queue, dict):
            return {"response_type": "query_answer", "status": "unconfirmed"}
        queue = player_queue.get("items", player_queue.get("queue", []))
        if not isinstance(queue, list):
            return {"response_type": "query_answer", "status": "unconfirmed"}
        items = []
        for row in queue[:MAX_SEARCH_ITEMS]:
            if isinstance(row, dict):
                items.append({
                    "title": _bounded_text(row.get("name") or row.get("title")),
                    "artist": _bounded_text(row.get("artist")),
                    "album": _bounded_text(row.get("album")),
                })
        current = player_queue.get("current_item")
        current_item = (
            {
                "title": _bounded_text(current.get("name") or current.get("title")),
                "artist": _bounded_text(current.get("artist")),
            }
            if isinstance(current, dict)
            else None
        )
        return {"response_type": "query_answer", "status": "ok",
                "current": current_item, "items": items}
