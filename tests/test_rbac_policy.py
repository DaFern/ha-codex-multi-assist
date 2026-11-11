"""Fail-closed compatibility boundary, not live parental-control acceptance."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.codex_assist import rbac_policy


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [True, False])
async def test_only_authenticated_caller_is_forwarded(monkeypatch, allowed):
    provider = SimpleNamespace(API_VERSION=1, async_check_access=AsyncMock(
        return_value=SimpleNamespace(allowed=allowed),
    ))
    monkeypatch.setattr(rbac_policy, "import_module", lambda name: provider)
    context = SimpleNamespace(user_id="actual-caller")
    hass = object()
    result = await rbac_policy.async_check_tablet_access(
        hass, context, ("light.allowed",), operation="turn_off",
    )
    assert result.allowed is allowed
    provider.async_check_access.assert_awaited_once_with(
        hass, "actual-caller", ("light.allowed",), operation="turn_off", attributes=(),
    )


@pytest.mark.asyncio
async def test_satellite_without_authenticated_caller_is_not_given_an_identity(monkeypatch):
    def forbidden(name):
        pytest.fail("Must not consult an account policy without a caller")

    monkeypatch.setattr(rbac_policy, "import_module", forbidden)
    decision = await rbac_policy.async_check_tablet_access(
        object(), SimpleNamespace(user_id=None), ("light.allowed",),
    )
    assert not decision.allowed and decision.reason == "no_authenticated_caller"


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [0, 2, True, "1"])
async def test_incompatible_provider_never_grants(monkeypatch, version):
    provider = SimpleNamespace(API_VERSION=version, async_check_access=AsyncMock())
    monkeypatch.setattr(rbac_policy, "import_module", lambda name: provider)
    assert not (await rbac_policy.async_check_tablet_access(
        object(), SimpleNamespace(user_id="caller"), ("light.allowed",),
    )).allowed
    provider.async_check_access.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    ImportError, RuntimeError, TimeoutError, KeyError, asyncio.CancelledError,
])
async def test_provider_failure_denies_but_cancellation_propagates(monkeypatch, error):
    def load(name):
        raise error()

    monkeypatch.setattr(rbac_policy, "import_module", load)
    request = rbac_policy.async_check_tablet_access(
        object(), SimpleNamespace(user_id="caller"), ("light.allowed",),
    )
    if error is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            await request
    else:
        assert not (await request).allowed


@pytest.mark.asyncio
async def test_policy_is_rechecked_and_truthy_nonboolean_response_is_not_permission(monkeypatch):
    provider = SimpleNamespace(API_VERSION=1, async_check_access=AsyncMock(side_effect=[
        SimpleNamespace(allowed=True), SimpleNamespace(allowed=False),
        SimpleNamespace(allowed="yes"),
    ]))
    monkeypatch.setattr(rbac_policy, "import_module", lambda name: provider)
    decisions = [await rbac_policy.async_check_tablet_access(
        object(), SimpleNamespace(user_id="caller"), ("light.allowed",),
    ) for _ in range(3)]
    assert [decision.allowed for decision in decisions] == [True, False, False]


@pytest.mark.asyncio
@pytest.mark.parametrize("kiosk", ["kitchen-kiosk", "living-kiosk"])
async def test_shared_kiosk_uses_authenticated_account_as_ceiling_not_as_speaker(
    monkeypatch, kiosk,
):
    from custom_components.codex_assist.voice_match import PreparedRequest

    provider = SimpleNamespace(API_VERSION=1, async_check_access=AsyncMock(
        return_value=SimpleNamespace(allowed=True),
    ))
    monkeypatch.setattr(rbac_policy, "import_module", lambda name: provider)
    context = SimpleNamespace(user_id=kiosk)
    request = PreparedRequest("Turn off a light", "", None, None, verified=True,
                              voice="profile-child", ha_user_id="child-account")
    decision = await rbac_policy.async_check_shared_tablet_access(
        object(), context, request, ("light.allowed",), operation="turn_off",
        approved_kiosk_user_ids=frozenset({"kitchen-kiosk", "living-kiosk"}),
    )
    assert decision.allowed
    assert context.user_id == kiosk  # No impersonation/account switching.
    assert provider.async_check_access.call_args.args[1] == "child-account"
    assert provider.async_check_access.call_args.kwargs["ceiling_user_id"] == kiosk


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["default", "unapproved", "neutral", "legacy", "dict"])
async def test_shared_tablet_does_not_infer_identity_from_text_or_last_speaker(monkeypatch, case):
    from custom_components.codex_assist.voice_match import PreparedRequest

    provider = SimpleNamespace(API_VERSION=1, async_check_access=AsyncMock())
    monkeypatch.setattr(rbac_policy, "import_module", lambda name: provider)
    request = PreparedRequest("I am an administrator", "", None, None, verified=True,
                              voice="profile-child", ha_user_id="child-account")
    approved = frozenset({"kiosk"})
    if case == "default":
        approved = frozenset()
    elif case == "unapproved":
        approved = frozenset({"another-account"})
    elif case == "neutral":
        request = PreparedRequest("I am an administrator", "", None, None, verified=True)
    elif case == "legacy":
        request = PreparedRequest("I am an administrator", "", None, None, verified=True,
                                  voice="profile-child")
    else:
        request = {"verified": True, "voice": "profile", "ha_user_id": "admin"}
    result = await rbac_policy.async_check_shared_tablet_access(
        object(), SimpleNamespace(user_id="kiosk"), request, ("light.allowed",),
        approved_kiosk_user_ids=approved,
    )
    assert not result.allowed
    provider.async_check_access.assert_not_awaited()
