"""Finite timer-policy version and lifetime checks, without device I/O."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.codex_assist import timer_policy


@pytest.mark.parametrize("version", [None, False, True, 2, "1"])
async def test_missing_or_incompatible_timer_oracle_is_never_a_grant(hass, monkeypatch, version):
    provider = SimpleNamespace(
        TIMER_POLICY_VERSION=version, async_check_timer_access=AsyncMock(),
    )
    monkeypatch.setattr(timer_policy, "_provider", lambda: provider)
    auth = SimpleNamespace(valid=lambda: True, role_id="guest")
    assert not await timer_policy.async_timer_access(hass, auth, "assist_satellite.test")
    provider.async_check_timer_access.assert_not_awaited()


@pytest.mark.parametrize("matched", [True, False])
async def test_original_verified_subject_and_exact_target_are_forwarded(hass, monkeypatch, matched):
    provider = SimpleNamespace(
        TIMER_POLICY_VERSION=1,
        async_check_timer_access=AsyncMock(return_value=SimpleNamespace(allowed=True)),
    )
    monkeypatch.setattr(timer_policy, "_provider", lambda: provider)
    auth = SimpleNamespace(valid=lambda: True, **(
        {"user_id": "speaker"} if matched else {"role_id": "guest"}
    ))
    assert await timer_policy.async_timer_access(
        hass, auth, "assist_satellite.test", action="cancel",
    )
    provider.async_check_timer_access.assert_awaited_once_with(
        hass, ("assist_satellite.test",), action="cancel", **(
            {"user_id": "speaker"} if matched else {"guest_role_id": "guest"}
        ),
    )


@pytest.mark.parametrize("allowed", [False, None, 1, "true"])
async def test_uncertain_or_denied_policy_result_is_not_truthy_authority(
    hass, monkeypatch, allowed,
):
    provider = SimpleNamespace(
        TIMER_POLICY_VERSION=1,
        async_check_timer_access=AsyncMock(return_value=SimpleNamespace(allowed=allowed)),
    )
    monkeypatch.setattr(timer_policy, "_provider", lambda: provider)
    auth = SimpleNamespace(valid=lambda: True, role_id="guest")
    assert not await timer_policy.async_timer_access(hass, auth, "assist_satellite.test")


async def test_revocation_during_policy_await_discards_the_answer(hass, monkeypatch):
    state = SimpleNamespace(current=True)

    async def policy(*args, **kwargs):
        state.current = False
        return SimpleNamespace(allowed=True)

    monkeypatch.setattr(timer_policy, "_provider", lambda: SimpleNamespace(
        TIMER_POLICY_VERSION=1, async_check_timer_access=policy,
    ))
    auth = SimpleNamespace(valid=lambda: state.current, role_id="guest")
    assert not await timer_policy.async_timer_access(hass, auth, "assist_satellite.test")


async def test_provider_failure_is_a_denial_without_fallback(hass, monkeypatch):
    monkeypatch.setattr(timer_policy, "_provider", lambda: SimpleNamespace(
        TIMER_POLICY_VERSION=1, async_check_timer_access=AsyncMock(side_effect=TimeoutError),
    ))
    auth = SimpleNamespace(valid=lambda: True, role_id="guest")
    assert not await timer_policy.async_timer_access(hass, auth, "assist_satellite.test")


async def test_catalogue_batch_is_one_oracle_request_not_per_target_awaits(hass, monkeypatch):
    provider = SimpleNamespace(
        TIMER_POLICY_VERSION=1,
        async_check_timer_access=AsyncMock(return_value=SimpleNamespace(allowed=True)),
    )
    monkeypatch.setattr(timer_policy, "_provider", lambda: provider)
    auth = SimpleNamespace(valid=lambda: True, user_id="speaker")
    ids = ("assist_satellite.a", "assist_satellite.b")
    assert await timer_policy.async_timer_access_batch(hass, auth, ids)
    provider.async_check_timer_access.assert_awaited_once_with(
        hass, ids, action="read", user_id="speaker",
    )


@pytest.mark.parametrize("ids", [[], (), ("assist_satellite.a",) * 2, ({"bad": "id"},)])
async def test_invalid_batch_cannot_reach_the_provider(hass, monkeypatch, ids):
    def forbidden():
        raise AssertionError("Invalid catalogue must not reach the provider")

    monkeypatch.setattr(timer_policy, "_provider", forbidden)
    auth = SimpleNamespace(valid=lambda: True, role_id="guest")
    assert not await timer_policy.async_timer_access_batch(hass, auth, ids)
