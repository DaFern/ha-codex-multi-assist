"""Inactive RBAC policy contract; no routes, tool grants or runtime hooks.

This foundation intentionally does not enable tablet/satellite Assist access.
The protected dispatcher, context filtering and admin satellite binding must be
complete before any caller wires this into request handling.
"""

import asyncio
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True)
class PolicyDecision:
    """A local fail-closed result without remote policy details."""

    allowed: bool = False
    reason: str = "unavailable"


async def async_check_tablet_access(
    hass, context, entity_ids, *, operation="read", attributes=(),
):
    """Evaluate only the authenticated caller, never a model-supplied account.

    This is a necessary policy check, not complete authorization to execute:
    exact native target binding and revocation rechecks remain mandatory.
    Shared satellites are deliberately unsupported by this initial interface.
    """
    user_id = getattr(context, "user_id", None)
    if not user_id:
        return PolicyDecision(reason="no_authenticated_caller")
    return await _async_check(
        hass, user_id, entity_ids, operation=operation, attributes=attributes,
    )


async def async_check_shared_tablet_access(
    hass, context, prepared_request, entity_ids, *, approved_kiosk_user_ids=frozenset(),
    operation="read", attributes=(),
):
    """Preflight an opt-in kiosk ceiling intersected with paired voice ownership.

    The approved account set must come from administrator-owned configuration,
    never client payloads. prepared_request must come from the paired verifier;
    no wire token, transcript, device_id or requested account is accepted here.
    This does not authenticate a satellite, replace Context or authorize execution.
    Per-turn object/transport binding and protected dispatch are still prerequisites.
    """
    from .voice_match import PreparedRequest

    caller = getattr(context, "user_id", None)
    if (not caller or not isinstance(approved_kiosk_user_ids, frozenset)
            or caller not in approved_kiosk_user_ids):
        return PolicyDecision(reason="unapproved_kiosk")
    if (not isinstance(prepared_request, PreparedRequest)
            or not prepared_request.verified or not prepared_request.voice
            or not prepared_request.ha_user_id):
        return PolicyDecision(reason="unverified_speaker")
    return await _async_check(
        hass, prepared_request.ha_user_id, entity_ids, operation=operation,
        attributes=attributes, ceiling_user_id=caller,
    )


async def _async_check(hass, user_id, entity_ids, *, operation, attributes,
                       ceiling_user_id=None):
    """Query current policy; return no reusable grant and never broaden failures."""
    try:
        provider = import_module("custom_components.ha_rbac.assist_policy")
        if type(provider.API_VERSION) is not int or provider.API_VERSION != 1:
            return PolicyDecision(reason="incompatible")
        async with asyncio.timeout(2):
            decision = await provider.async_check_access(
                hass, user_id, entity_ids, operation=operation, attributes=attributes,
                **({"ceiling_user_id": ceiling_user_id} if ceiling_user_id else {}),
            )
        if type(decision.allowed) is not bool:
            return PolicyDecision(reason="invalid_response")
        return PolicyDecision(decision.allowed, "allowed" if decision.allowed else "denied")
    except Exception:
        # Provider bugs must deny, never trigger a broader tool/identity fallback.
        # asyncio cancellation derives from BaseException and still propagates.
        return PolicyDecision()
