"""Inactive exact-target native Assist adapter; no routes or tool registration.

Trusted server code owns one guard per entry and supplies paired PreparedRequests.
This is not speaker authentication or transport provenance. Never pass free text
through the normal intent matcher after checking an exact command here.
"""

import asyncio
import re
import time
import weakref
from dataclasses import dataclass, field
from types import SimpleNamespace

from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import intent

from .rbac_policy import async_check_shared_tablet_access
from .voice_match import PreparedRequest

MAX_COMMANDS = 256
COMMAND_TTL = 30
ENTITY_ID = re.compile(r"(?:light|fan)\.[a-z0-9_]+\Z")


@dataclass(frozen=True, eq=False)
class ExactCommand:
    """Opaque single-use proposal, not an authorization grant."""

    operation: str
    entity_ids: tuple[str, ...] = field(repr=False)
    _context: object = field(repr=False)
    _request: PreparedRequest = field(repr=False)
    _caller: str = field(repr=False)
    _identities: tuple = field(repr=False)
    _expires: float = field(repr=False)


@dataclass(frozen=True)
class ExecutionResult:
    """Command acceptance, never a claim of physical completion or rollback."""

    status: str = "denied"
    completed: int = 0


class _AwaitedHandler(intent.ServiceIntentHandler):
    """Keep native exact-entity service construction, without timeout detachment."""

    async def _run_then_background(self, task):
        await task  # Cancellation also cancels the child; no shield/background retry.


class _Denied(Exception):
    """Private fixed-code denial, without target or policy details."""


class SharedExecutionGuard:
    """Entry-owned command ledger. Do not construct a new ledger for each call.

    Both native-first resolution and model requests must supply exact IDs to
    prepare(), then execute the returned object with the original caller/turn.
    Resolution itself must use protected context, not unrestricted HA names.
    No public ingress, normal intent forwarding or model tools are enabled here.
    """

    def __init__(self, hass, *, approved_kiosk_user_ids=frozenset(), request_is_current=None):
        self.hass = hass
        self.approved_kiosk_user_ids = approved_kiosk_user_ids
        self._pending = {}
        self._turns = {}
        self._closed = False
        self._request_is_current = request_is_current

    def close(self):
        """Invalidate outstanding proposals on unload/configuration changes."""
        self._closed = True
        self._pending.clear()

    def _identity(self, eid):
        entry = er.async_get(self.hass).async_get(eid)
        if (entry is None or entry.disabled_by is not None
                or entry.platform in {"group", "template"}):
            return None
        return (entry.id, entry.unique_id, entry.platform)

    def _eligible(self, context, prepared):
        caller = getattr(context, "user_id", None)
        return (not self._closed and isinstance(caller, str) and bool(caller)
                and isinstance(self.approved_kiosk_user_ids, frozenset)
                and caller in self.approved_kiosk_user_ids
                and isinstance(prepared, PreparedRequest) and prepared.verified is True
                and bool(prepared.voice) and bool(prepared.ha_user_id))

    def prepare(self, context, prepared_request, entity_ids, *, operation):
        """Seal one immutable, bounded proposal per exact prepared voice turn.

        Does not cache a policy decision. IDs and operation can originate from a
        model, but caller, PreparedRequest and kiosk approvals must never do so.
        """
        now = time.monotonic()
        self._pending = {key: cmd for key, cmd in self._pending.items() if cmd._expires > now}
        if (not self._eligible(context, prepared_request)
                or operation not in ("turn_on", "turn_off")
                or not isinstance(entity_ids, tuple) or not 0 < len(entity_ids) <= 32
                or any(not isinstance(eid, str) or not ENTITY_ID.fullmatch(eid)
                       for eid in entity_ids)
                or len(set(entity_ids)) != len(entity_ids)
                or id(prepared_request) in self._turns
                or len(self._turns) >= MAX_COMMANDS):
            return None
        identities = tuple(self._identity(eid) for eid in entity_ids)
        if any(identity is None for identity in identities):
            return None
        command = ExactCommand(operation, entity_ids, context, prepared_request,
                               context.user_id, identities, now + COMMAND_TTL)
        key = id(prepared_request)
        self._turns[key] = weakref.ref(prepared_request, lambda _: self._turns.pop(key, None))
        self._pending[id(command)] = command
        return command

    def _bound(self, command, context, prepared):
        return (self._eligible(context, prepared)
                and command._context is context and command._request is prepared
                and context.user_id == command._caller
                and command._expires > time.monotonic()
                and (self._request_is_current is None
                     or self._request_is_current(context, prepared) is True))

    async def _check(self, command, context, prepared):
        if not self._bound(command, context, prepared):
            return False
        decision = await async_check_shared_tablet_access(
            self.hass, context, prepared, command.entity_ids,
            approved_kiosk_user_ids=self.approved_kiosk_user_ids, operation=command.operation,
        )
        # The provider resolves BOTH accounts before synchronous policy checks.
        # No scheduling point is allowed after this final check and native
        # service admission. Recheck identity/exposure/state after the auth awaits.
        if not decision.allowed or not self._bound(command, context, prepared):
            return False
        for eid, identity in zip(command.entity_ids, command._identities, strict=True):
            state = self.hass.states.get(eid)
            if (self._identity(eid) != identity or state is None
                    or state.state in {"unknown", "unavailable"}
                    or "entity_id" in state.attributes
                    or not async_should_expose(self.hass, "conversation", eid)):
                return False
        return True

    async def async_execute(self, command, *, context, prepared_request):
        """Consume before any await; reject concurrent replay and mismatched turns.

        Check the WHOLE batch before the first command and again inside every
        native execution task, immediately before service admission. Later policy
        revocation stops remaining targets; already-admitted actions cannot be
        undone. Failure/cancellation is never retried or forwarded elsewhere.
        """
        if (not isinstance(command, ExactCommand)
                or self._pending.pop(id(command), None) is not command):
            return ExecutionResult()
        completed = 0
        try:
            if not await self._check(command, context, prepared_request):
                return ExecutionResult()
            for eid in command.entity_ids:
                claimed = False
                admitted = False

                async def guarded_call(
                    domain, service, service_data, *, context, blocking, _eid=eid,
                ):
                    nonlocal admitted, claimed
                    # This runs INSIDE the task created by the native handler.
                    if (claimed or domain != _eid.partition(".")[0]
                            or service != command.operation or service_data != {"entity_id": _eid}
                            or context is not command._context or blocking is not True):
                        raise _Denied()
                    claimed = True  # Consume this native admission before policy awaits, too.
                    if not await self._check(command, context, prepared_request):
                        raise _Denied()
                    admitted = True
                    await self.hass.services.async_call(
                        domain, service, {"entity_id": _eid}, context=context, blocking=True,
                    )

                # Request-local facade only: no HA/global handler monkeypatching.
                native_hass = SimpleNamespace(
                    services=SimpleNamespace(async_call=guarded_call),
                    async_create_task_internal=self.hass.async_create_task_internal,
                )
                native_intent = intent.Intent(
                    native_hass, "codex_assist", "CodexProtectedExactCommand", {}, None,
                    context, "en", assistant="conversation",
                )
                handler = _AwaitedHandler(
                    "CodexProtectedExactCommand", eid.partition(".")[0], command.operation,
                )
                await handler.async_call_service(
                    eid.partition(".")[0], command.operation, native_intent,
                    self.hass.states.get(eid),
                )
                if not admitted:
                    raise _Denied()  # Unsupported native behavior cannot report success.
                completed += 1
        except asyncio.CancelledError:
            raise
        except _Denied:
            return ExecutionResult("partial" if completed else "denied", completed)
        except Exception:
            # Do not expose policy details, target names, raw responses or errors.
            return ExecutionResult("partial" if completed else "unconfirmed", completed)
        return ExecutionResult("completed", completed)
