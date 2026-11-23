"""Fail-closed client for the separate finite RBAC timer oracle."""

import asyncio

from .guest_policy import _provider


async def async_timer_access(hass, auth, satellite_id, *, action="read"):
    return await async_timer_access_batch(hass, auth, (satellite_id,), action=action)


async def async_timer_access_batch(hass, auth, satellite_ids, *, action="read"):
    """One oracle check after subject resolution, with no per-target await race."""
    if (
        type(satellite_ids) is not tuple or not 0 < len(satellite_ids) <= 32
        or any(type(eid) is not str or not eid.startswith("assist_satellite.")
               for eid in satellite_ids)
        or len(set(satellite_ids)) != len(satellite_ids)
        or type(action) is not str or action not in {"read", "cancel", "stop", "cancel_all"}
    ):
        return False
    try:
        provider = _provider()
        version = getattr(provider, "TIMER_POLICY_VERSION", None)
        if type(version) is not int or version != 1 or not auth.valid():
            return False
        subject = (
            {"user_id": auth.user_id} if hasattr(auth, "user_id")
            else {"guest_role_id": auth.role_id}
        )
        async with asyncio.timeout(2):
            result = await provider.async_check_timer_access(
                hass, satellite_ids, action=action, **subject,
            )
        return auth.valid() and getattr(result, "allowed", None) is True
    except Exception:
        return False
