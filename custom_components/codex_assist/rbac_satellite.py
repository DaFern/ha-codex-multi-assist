"""Admission-bound satellite dispatcher; not registered with any live transport.

This connects the in-process transport contract to the exact native guard.
It does not intercept ESPHome, enable ordinary HA sentence triggers/local intents,
resolve free speech, call a model, or authenticate a self-declared satellite ID.
"""

import asyncio
import hashlib
import json
from types import SimpleNamespace

from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.core import Context

from .rbac_execution import ExecutionResult, SharedExecutionGuard
from .rbac_policy import import_module
from .speaker_packet import PacketError, decode
from .voice_match import PreparedRequest


class SatelliteExecutionGuard(SharedExecutionGuard):
    """Reuse exact native admission while replacing only the kiosk policy lookup."""

    def __init__(self, hass, *, request_is_current, guest_role_for_request):
        super().__init__(hass, request_is_current=request_is_current)
        self._guest_role_for_request = guest_role_for_request

    def _eligible(self, context, prepared):
        return (
            not self._closed
            and isinstance(context, Context)
            and isinstance(prepared, PreparedRequest)
            and prepared.verified is True
            and (
                (prepared.voice is None and prepared.ha_user_id is None)
                or (bool(prepared.voice) and bool(prepared.ha_user_id))
            )
            and callable(self._request_is_current)
            and self._request_is_current(context, prepared) is True
        )

    async def _check(self, command, context, prepared):
        if not self._bound(command, context, prepared):
            return False
        try:
            provider = import_module("custom_components.ha_rbac.assist_policy")
            if (
                type(provider.SATELLITE_API_VERSION) is not int
                or provider.SATELLITE_API_VERSION != 1
            ):
                return False
            subject = (
                {"user_id": prepared.ha_user_id}
                if prepared.voice is not None
                else {"guest_role_id": self._guest_role_for_request(prepared)}
            )
            async with asyncio.timeout(2):
                decision = await provider.async_check_satellite_access(
                    self.hass, command.entity_ids, operation=command.operation, **subject,
                )
            if decision.allowed is not True or not self._bound(command, context, prepared):
                return False
            # There must be no await between these checks and native admission.
            for eid, identity in zip(command.entity_ids, command._identities, strict=True):
                state = self.hass.states.get(eid)
                if (
                    self._identity(eid) != identity
                    or state is None
                    or state.state in {"unknown", "unavailable"}
                    or "entity_id" in state.attributes
                    or not async_should_expose(self.hass, "conversation", eid)
                ):
                    return False
        except Exception:
            return False
        return True


class ProtectedSatelliteDispatcher:
    """Entry-owned paired STT -> fresh RBAC projection -> exact native execution."""

    SATELLITE_DISPATCH_VERSION = 1

    @classmethod
    def for_entry(cls, hass, entry, *, candidate_entity_ids):
        """Read administrator-owned settings dynamically, without registering ingress."""
        from .guest_policy import CONF_GUEST_ROLE
        from .voice_match import CONF_VOICE_MATCH_KEY, runtime_for_entry

        return cls(
            hass, runtime_for_entry(entry),
            key_provider=lambda: entry.options.get(CONF_VOICE_MATCH_KEY, ""),
            guest_role_provider=lambda: entry.options.get(CONF_GUEST_ROLE),
            candidate_entity_ids=candidate_entity_ids,
        )

    def __init__(
        self, hass, runtime, *, key_provider, guest_role_provider, candidate_entity_ids,
    ):
        self.hass = hass
        self._runtime = runtime
        self._key_provider = key_provider
        self._guest_role_provider = guest_role_provider
        self._candidates = candidate_entity_ids
        self._validator = None
        self._closed = False
        self._scopes = {}
        self._tasks = set()
        self._guard = SatelliteExecutionGuard(
            hass, request_is_current=self._current, guest_role_for_request=self._guest_role,
        )

    def bind_satellite_ingress(self, validator):
        """Trusted registration only; the callback checks the original live lease."""
        if self._closed or self._validator is not None or not callable(validator):
            return False
        self._validator = validator
        return True

    def _guest_role(self, prepared):
        scope = self._scopes.get(id(prepared))
        return scope[3] if scope is not None and scope[0] is prepared else None

    def _current(self, context, prepared):
        scope = self._scopes.get(id(prepared))
        try:
            return bool(
                not self._closed
                and scope is not None
                and scope[0] is prepared
                and scope[1].context is context
                and self._validator(scope[1]) is True
                and hashlib.sha256(self._key_provider().encode()).digest() == scope[2]
                and (
                    prepared.voice is not None
                    or self._guest_role_provider() == scope[3]
                )
            )
        except Exception:
            return False

    def close(self):
        """Invalidate authority first; embedding lifecycle must await cancelled tasks."""
        self._closed = True
        self._guard.close()
        for task in tuple(self._tasks):
            if task is not asyncio.current_task():
                task.cancel()

    async def async_guest_turn(self, admission, *, transcript, handler):
        """Retain the neutral-only contract for existing trusted callers."""
        return await self._async_tool_turn(
            admission, transcript=transcript, handler=handler, neutral_only=True,
        )

    async def async_voice_turn(self, admission, *, transcript, handler):
        """Select own-user or guest authority only from the private STT handoff."""
        return await self._async_tool_turn(
            admission, transcript=transcript, handler=handler, neutral_only=False,
        )

    async def _async_tool_turn(self, admission, *, transcript, handler, neutral_only):
        """Supply scoped guest tools only inside a live, one-use transport admission.

        The trusted existing-Kiosk adapter must own handler, which may run a model
        using only the returned protected prompt/tools, never the general Assist API.
        No transport adapter is registered by this source-only method.
        """
        denied = {"status": "denied", "completed": 0}
        if (
            self._closed or self._validator is None
            or self._validator(admission) is not True
            or admission.owner is not asyncio.current_task()
            or not callable(handler)
        ):
            return denied
        prepared = None
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            from .guest_control import (
                GuestAuthorization,
                MatchedAuthorization,
                async_guest_tools,
            )

            key = self._key_provider()
            wire = self._runtime.handoffs.consume(
                key, transcript, not_before=admission.issued,
            )
            if wire is None:
                return denied
            prepared = self._runtime.prepare_request(
                key, transcript, [SimpleNamespace(role="user", content=transcript)],
                None, "protected_guest_voice", packet_text=wire,
            )
            matched = prepared.voice is not None
            role_id = None if matched else self._guest_role_provider()
            candidates = self._candidates() if callable(self._candidates) else self._candidates
            if (
                not prepared.verified
                or (matched and (neutral_only or not prepared.ha_user_id))
                or (not matched and (
                    prepared.ha_user_id is not None
                    or type(role_id) is not str or not 0 < len(role_id) <= 128
                ))
                or type(candidates) is not tuple
                or not 0 < len(candidates) <= 1024
                or any(type(eid) is not str for eid in candidates)
                or len(set(candidates)) != len(candidates)
            ):
                return denied
            self._scopes[id(prepared)] = (
                prepared, admission, hashlib.sha256(key.encode()).digest(), role_id,
            )
            if matched:
                authorization = MatchedAuthorization(
                    admission.context, prepared, prepared.ha_user_id,
                    admission.connection.satellite_id, request_is_current=self._current,
                    expires=admission.expires,
                )
            else:
                authorization = GuestAuthorization(
                    admission.context, prepared, role_id, admission.connection.satellite_id,
                    request_is_current=self._current, selected_role=self._guest_role_provider,
                    expires=admission.expires,
                )
            payload = await async_guest_tools(
                self.hass, authorization, candidates,
                player_ids=tuple(eid for eid in candidates
                                 if eid.startswith("media_player.")),
            )
            if payload is None or not payload["tools"] or not authorization.valid():
                return denied
            # Stable continuity subject from this newly consumed, verified packet,
            # not a remembered account or a client/model conversation identifier.
            _clean, packet, _issued = decode(key, wire)
            payload["continuation_identity"] = hashlib.sha256(json.dumps([
                hashlib.sha256(key.encode()).hexdigest(), prepared.voice,
                prepared.ha_user_id, packet["revision"], prepared.speaker_name,
                prepared.instructions, role_id, admission.context.user_id,
            ]).encode()).hexdigest()
            result = await handler(payload, admission.context)
            return result if authorization.valid() and await payload["validate"]() else denied
        except PacketError:
            return denied
        except asyncio.CancelledError:
            raise
        except Exception:
            return {"status": "unconfirmed", "completed": 0}
        finally:
            self._tasks.discard(task)
            if prepared is not None:
                self._scopes.pop(id(prepared), None)

    async def async_dispatch(self, admission, *, transcript, command):
        """Accept only a same-task STT handoff and a bounded exact on/off proposal.

        The existing paired protocol encodes an explicit neutral result as v1;
        recognized v1 profiles without an enrolled account remain denied. Raw or
        serialized packets are never accepted in place of the private handoff.
        Transport provenance is a separate prerequisite supplied by admission.
        """
        denied = {"status": "denied", "completed": 0}
        if (
            self._closed
            or self._validator is None
            or self._validator(admission) is not True
            or admission.owner is not asyncio.current_task()
        ):
            return denied
        prepared = None
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            key = self._key_provider()
            if not isinstance(key, str) or not key:
                return denied
            wire = self._runtime.handoffs.consume(
                key, transcript, not_before=admission.issued,
            )
            if wire is None:
                return denied
            prepared = self._runtime.prepare_request(
                key, transcript, [SimpleNamespace(role="user", content=transcript)],
                None, "protected_satellite_exact", packet_text=wire,
            )
            if not prepared.verified:
                return denied
            if prepared.voice is not None and not prepared.ha_user_id:
                return denied
            guest_role = self._guest_role_provider() if prepared.voice is None else None
            if prepared.voice is None and (
                prepared.ha_user_id is not None
                or not isinstance(guest_role, str)
                or not guest_role
            ):
                return denied
            if (
                type(command) is not dict
                or set(command) != {"operation", "entity_ids"}
                or type(command["operation"]) is not str
                or command["operation"] not in {"turn_on", "turn_off"}
                or type(command["entity_ids"]) is not list
                or not 0 < len(command["entity_ids"]) <= 32
                or any(type(eid) is not str for eid in command["entity_ids"])
                or not isinstance(self._candidates, tuple)
                or not 0 < len(self._candidates) <= 32
                or any(type(eid) is not str for eid in self._candidates)
            ):
                return denied
            operation, targets = command["operation"], tuple(command["entity_ids"])
            if (
                len(set(targets)) != len(targets)
                or any(eid not in self._candidates or len(eid) > 255 for eid in targets)
            ):
                return denied
            self._scopes[id(prepared)] = (
                prepared, admission, hashlib.sha256(key.encode()).digest(), guest_role,
            )
            provider = import_module("custom_components.ha_rbac.assist_policy")
            if (
                type(provider.SATELLITE_API_VERSION) is not int
                or provider.SATELLITE_API_VERSION != 1
            ):
                return denied
            subject = (
                {"user_id": prepared.ha_user_id}
                if prepared.voice is not None else {"guest_role_id": guest_role}
            )
            async with asyncio.timeout(2):
                projection = await provider.async_project_satellite_context(
                    self.hass, self._candidates, **subject,
                )
            if (
                not self._current(admission.context, prepared)
                or type(projection) is not dict
                or set(projection) != {"available", "entities"}
                or projection["available"] is not True
                or type(projection["entities"]) is not list
                or len(projection["entities"]) > 32
                or any(
                    type(row) is not dict
                    or type(row.get("entity_id")) is not str
                    or row["entity_id"] not in self._candidates
                    for row in projection["entities"]
                )
            ):
                return denied
            readable = {row["entity_id"] for row in projection["entities"]}
            if any(eid not in readable for eid in targets):
                return denied
            proposal = self._guard.prepare(
                admission.context, prepared, targets, operation=operation,
            )
            result = (
                await self._guard.async_execute(
                    proposal, context=admission.context, prepared_request=prepared,
                )
                if proposal is not None else ExecutionResult()
            )
            return {"status": result.status, "completed": result.completed}
        except PacketError:
            return denied
        except asyncio.CancelledError:
            raise
        except Exception:
            return {"status": "unconfirmed", "completed": 0}
        finally:
            self._tasks.discard(task)
            if prepared is not None:
                self._scopes.pop(id(prepared), None)
