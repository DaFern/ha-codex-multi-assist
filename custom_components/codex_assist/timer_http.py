"""Authenticated exact-ID kiosk timer controls; no intents or service-call bridge."""

import asyncio
import json
import re
import secrets
import time
from dataclasses import dataclass

from aiohttp import web
from homeassistant.components.http import KEY_HASS_USER, HomeAssistantView
from homeassistant.components.intent.const import TIMER_DATA
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from .guest_policy import _provider
from .satellite_timers import MAX_SECONDS

DATA_API = "codex_assist_exact_timer_http"
API = "codex_assist.exact_timers"
VERSION = 1
URL = "/api/codex_assist/timers/v1"
ACTIONS = frozenset({"pause", "resume", "cancel", "add", "remove"})
NONCE_SECONDS = 30
MAX_NONCES = 256
MAX_BODY = 4096


@dataclass
class Registration:
    entry: object


class TimerApi:
    """Entry-owned enrollment plus bounded, single-use, account-bound operation nonces."""

    def __init__(self, hass):
        self.hass = hass
        self.entries = {}
        self.nonces = {}

    def owner(self, satellite_id):
        matches = [
            registration for registration in self.entries.values()
            if registration.entry.state is ConfigEntryState.LOADED
            and self.hass.config_entries.async_get_entry(registration.entry.entry_id)
            is registration.entry
            and satellite_id in registration.entry.options.get("protected_satellite_ids", [])
        ]
        return matches[0] if len(matches) == 1 else None

    def nonce(self, user_id):
        now = time.monotonic()
        self.nonces = {key: row for key, row in self.nonces.items() if row[1] > now}
        if len(self.nonces) >= MAX_NONCES:
            return None
        value = secrets.token_hex(24)
        self.nonces[value] = (user_id, now + NONCE_SECONDS)
        return value

    def consume(self, nonce, user_id):
        row = self.nonces.get(nonce)
        if row is None or row[0] != user_id:
            return False
        self.nonces.pop(nonce)
        return row[1] > time.monotonic()


def register_timer_api(hass, entry):
    """Register once; unloaded/changed enrollment never leaves an active control grant."""
    api = hass.data.get(DATA_API)
    if api is None:
        api = hass.data[DATA_API] = TimerApi(hass)
        hass.http.register_view(ExactTimerView(api))
    registration = api.entries[entry.entry_id] = Registration(entry)

    def remove():
        if api.entries.get(entry.entry_id) is registration:
            api.entries.pop(entry.entry_id)
        if not api.entries:
            api.nonces.clear()

    return remove


def _response(http_status=200, **data):
    return web.json_response({"api": API, "version": VERSION, **data}, status=http_status,
                             headers={"Cache-Control": "no-store"})


def _user(request):
    # No signed-URL, anonymous, client-supplied identity or guest-role substitution.
    user = request.get(KEY_HASS_USER)
    if (
        not request.headers.get("Authorization", "").startswith("Bearer ")
        or user is None or not user.is_active or user.system_generated
    ):
        return None
    return user


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


def _valid(data):
    if type(data) is not dict or not {
        "entity_id", "timer_id", "action", "nonce",
    } <= set(data) or not set(data) <= {
        "entity_id", "timer_id", "action", "nonce", "seconds",
    }:
        return False
    for key, pattern in (
        ("entity_id", r"assist_satellite\.[a-z0-9_]{1,200}"),
        ("timer_id", r"[A-Za-z0-9_-]{1,128}"),
        ("nonce", r"[a-f0-9]{48}"),
    ):
        if type(data[key]) is not str or re.fullmatch(pattern, data[key]) is None:
            return False
    action = data["action"]
    if type(action) is not str or action not in ACTIONS:
        return False
    if action in {"add", "remove"}:
        return type(data.get("seconds")) is int and 0 < data["seconds"] <= MAX_SECONDS
    return "seconds" not in data


class ExactTimerView(HomeAssistantView):
    """A finite UI API under HA's native bearer authentication, not a public ingress."""

    url = URL
    name = "api:codex_assist:exact_timers"
    requires_auth = True

    def __init__(self, api):
        self.api = api

    async def get(self, request):
        user = _user(request)
        if user is None:
            return _response(403, error="denied")
        if not any(
            registration.entry.state is ConfigEntryState.LOADED
            for registration in self.api.entries.values()
        ):
            return _response(503, error="unavailable")
        nonce = self.api.nonce(user.id)
        if nonce is None:
            return _response(429, error="busy")
        return _response(actions=sorted(ACTIONS), nonce=nonce, expires_in=NONCE_SECONDS)

    async def post(self, request):
        user = _user(request)
        if user is None:
            return _response(403, error="denied")
        if request.content_type != "application/json":
            return _response(415, error="invalid_request")
        try:
            body = bytearray()
            async for chunk in request.content.iter_chunked(1024):
                body.extend(chunk)
                if len(body) > MAX_BODY:
                    return _response(413, error="invalid_request")
            data = json.loads(body.decode("utf-8"), object_pairs_hook=_object)
        except (ValueError, UnicodeError):
            return _response(400, error="invalid_request")
        if not _valid(data):
            return _response(400, error="invalid_request")
        if not self.api.consume(data["nonce"], user.id):
            return _response(409, error="expired_or_used_nonce")
        return await self.control(user.id, data)

    async def control(self, user_id, data):
        hass = self.api.hass
        eid, timer_id, action = (data[key] for key in ("entity_id", "timer_id", "action"))
        registration = self.api.owner(eid)
        if registration is None:
            return _response(403, error="denied")
        entry = registration.entry
        options = entry.options
        registry = er.async_get(hass)
        identity = registry.async_get(eid)
        manager = hass.data.get(TIMER_DATA)
        if (
            identity is None or identity.platform != "esphome"
            or identity.disabled_by is not None or not identity.device_id
            or manager is None
        ):
            return _response(403, error="denied")
        handler = manager.handlers.get(identity.device_id)
        timer = manager.timers.get(timer_id)
        # Do not disclose existence/ownership until the account is freshly authorised.
        try:
            provider = _provider()
            version = getattr(provider, "TIMER_CONTROL_POLICY_VERSION", None)
            if type(version) is not int or version != 1:
                return _response(503, error="policy_unavailable")
            async with asyncio.timeout(2):
                decision = await provider.async_check_timer_control_access(
                    hass, (eid,), action=action, user_id=user_id,
                )
            if getattr(decision, "allowed", None) is not True:
                return _response(403, error="denied")
        except Exception:
            return _response(503, error="policy_unavailable")
        # Everything after the final policy await, through the exact effect, is
        # synchronous. Registry, runtime, lifecycle and timer objects must still match.
        if (
            self.api.owner(eid) is not registration or entry.options is not options
            or registry.async_get(eid) is not identity or hass.data.get(TIMER_DATA) is not manager
            or not callable(handler) or manager.handlers.get(identity.device_id) != handler
        ):
            return _response(403, error="denied")
        if (
            timer is None or manager.timers.get(timer_id) is not timer
            or timer.device_id != identity.device_id or timer.conversation_command
        ):
            return _response(404, error="timer_not_found")
        seconds = data.get("seconds", 0)
        if action == "add" and timer.seconds_left + seconds > MAX_SECONDS:
            return _response(400, error="duration_limit")
        try:
            if action == "pause":
                if timer.is_active:
                    manager.pause_timer(timer_id)
            elif action == "resume":
                if not timer.is_active:
                    manager.unpause_timer(timer_id)
            elif action == "cancel":
                manager.cancel_timer(timer_id)
            else:
                manager.add_time(timer_id, seconds if action == "add" else -seconds)
        except Exception:
            # The callback may have already sent an event. No retry/fallback is safe.
            return _response(502, error="unconfirmed")
        return _response(status="accepted", timer_id=timer_id, action=action)
