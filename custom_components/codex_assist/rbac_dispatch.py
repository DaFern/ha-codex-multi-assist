"""Dormant protected ingress -> paired handoff -> context -> exact native guard.

No setup imports, network registration, proxy exceptions or model/tool activation.
Only structured exact commands are supported; free-text resolution is NOT enabled.
"""

import asyncio
import hashlib
import json
from types import SimpleNamespace

from .rbac_context import async_build_shared_context
from .rbac_execution import ExecutionResult, SharedExecutionGuard
from .speaker_packet import PacketError


class ProtectedDispatcher:
    """One per entry, with its existing SpeakerRuntime (nonce cache/handoffs).

    key_provider and candidate IDs are server-owned configuration, not payload
    arguments. The registry validator must remain live through native admission.
    """

    INGRESS_API_VERSION = 1

    def __init__(self, hass, runtime, *, key_provider, kiosk_user_ids, candidate_entity_ids):
        self.hass = hass
        self._runtime = runtime
        self._key_provider = key_provider
        self._candidates = candidate_entity_ids
        self._validator = None
        self._closed = False
        self._scopes = {}
        self._tasks = set()
        self._guard = SharedExecutionGuard(
            hass, approved_kiosk_user_ids=kiosk_user_ids, request_is_current=self._current,
        )

    def bind_ingress(self, validator):
        """Trusted registration handshake, never a public/client-selected callback."""
        if self._closed or self._validator is not None or not callable(validator):
            return False
        self._validator = validator
        return True

    def _current(self, context, prepared):
        scope = self._scopes.get(id(prepared))
        return bool(
            not self._closed and scope is not None and scope[0] is prepared
            and scope[1].context is context and self._validator(scope[1]) is True
            and hashlib.sha256(self._key_provider().encode()).digest() == scope[2]
        )

    def close(self):
        """Revoke guards first, then cancel active parent pipelines (no detach)."""
        self._closed = True
        self._guard.close()
        for task in tuple(self._tasks):
            if task is not asyncio.current_task():
                task.cancel()

    async def async_dispatch(self, admission, *, transcript, command):
        """Deny raw packets, serialized clean text, fake prepared users and history."""
        denied = {"status": "denied", "completed": 0}
        if (self._closed or self._validator is None or self._validator(admission) is not True
                or admission.owner is not asyncio.current_task()):
            return denied
        prepared = None
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            key = self._key_provider()
            if not isinstance(key, str) or not key:
                return denied
            wire = self._runtime.handoffs.consume(key, transcript)
            if wire is None:
                return denied
            # Fresh one-turn contents only. No unrestricted history or templates.
            prepared = self._runtime.prepare_request(
                key, transcript, [SimpleNamespace(role="user", content=transcript)],
                None, "protected_exact", packet_text=wire,
            )
            if not prepared.verified or not prepared.voice or not prepared.ha_user_id:
                return denied
            if (type(command) is not dict or set(command) != {"operation", "entity_ids"}
                    or type(command["operation"]) is not str
                    or command["operation"] not in ("turn_on", "turn_off")
                    or type(command["entity_ids"]) is not list
                    or not 0 < len(command["entity_ids"]) <= 32
                    or any(type(eid) is not str or len(eid) > 255 for eid in command["entity_ids"])
                    or not isinstance(self._candidates, tuple)
                    or not 0 < len(self._candidates) <= 32):
                return denied
            # Freeze the entire proposal before policy awaits; caller mutation
            # cannot change an action/target between context filtering and control.
            operation, targets = command["operation"], tuple(command["entity_ids"])
            if (len(set(targets)) != len(targets)
                    or any(eid not in self._candidates for eid in targets)):
                return denied
            self._scopes[id(prepared)] = (
                prepared, admission, hashlib.sha256(key.encode()).digest(),
            )
            snapshot = await async_build_shared_context(
                self.hass, admission.context, prepared, self._candidates,
                approved_kiosk_user_ids=self._guard.approved_kiosk_user_ids,
            )
            if not snapshot.available or not self._current(admission.context, prepared):
                return denied
            readable = {row["entity_id"] for row in json.loads(snapshot.text)["entities"]}
            if any(eid not in readable for eid in targets):
                return denied
            proposal = self._guard.prepare(
                admission.context, prepared, targets, operation=operation,
            )
            result = (await self._guard.async_execute(
                proposal, context=admission.context, prepared_request=prepared,
            )) if proposal is not None else ExecutionResult()
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
