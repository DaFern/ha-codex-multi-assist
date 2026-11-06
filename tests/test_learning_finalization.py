"""Read-only completion polling has bounded time, scope and operation authority."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.codex_assist.learning import finalization
from custom_components.codex_assist.learning.learning_bridge_protocol import BridgeError


def state(**changes):
    return {
        "id": "profile",
        "target": 30,
        "count": 29,
        "outcome": "active",
        "processing": True,
        "error": False,
        "notice": False,
        **changes,
    }


@pytest.fixture
def scope(monkeypatch):
    monkeypatch.setattr(finalization, "POLL_INTERVAL", 0)
    frame = SimpleNamespace(valid=True)
    flow = SimpleNamespace(
        prompt_count=29,
        user_id="user",
        profile_id="profile",
        credentials={"session_token": "synthetic"},
        must_reconsent=False,
        expires=time.monotonic() + 120,
    )

    def check(frame):
        if not frame.valid:
            raise ValueError("revoked")

    controller = SimpleNamespace(
        check=check,
        closing=False,
        key=lambda frame: "scope",
        flows={"scope": flow},
        bridge=SimpleNamespace(call=AsyncMock()),
    )
    return controller, flow, frame


async def wait(scope, initial=None):
    return await finalization.wait_for_final_state(*scope, state() if initial is None else initial)


@pytest.mark.asyncio
@pytest.mark.parametrize("reload_pending", [False, True])
async def test_final_completion_requires_only_read_only_checks(scope, reload_pending):
    controller, flow, _ = scope
    completed = state(count=30, processing=reload_pending, outcome="complete")
    controller.bridge.call.side_effect = [state(count=30), completed]
    assert await wait(scope) == completed
    assert controller.bridge.call.await_count == 2
    for call in controller.bridge.call.await_args_list:
        assert call.args == ("state", "user", flow.credentials)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"processing": False},
        {"error": True},
        {"outcome": "paused"},
        {"outcome": "cancelled"},
        {"outcome": "complete", "processing": False},
        {"target": "30"},
        {"target": True},
        {"target": 0},
        {"target": 101},
    ],
)
async def test_non_waiting_states_do_not_query_backend(scope, changes):
    original = state(**changes)
    assert await wait(scope, original) is original
    scope[0].bridge.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_intermediate_sample_does_not_wait(scope):
    scope[1].prompt_count = 2
    original = state()
    assert await wait(scope, original) is original
    scope[0].bridge.call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"error": True},
        {"outcome": "paused", "processing": False},
        {"outcome": "cancelled", "processing": False},
        {"outcome": "expired", "processing": False},
        {"processing": False, "notice": True},
    ],
)
async def test_non_success_and_rejected_sample_return_without_more_checks(scope, changes):
    outcome = state(**changes)
    scope[0].bridge.call.return_value = outcome
    assert await wait(scope) == outcome
    assert scope[0].bridge.call.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"id": "someone-else"},
        {"target": 29},
        {"count": True},
        {"count": 31},
        {"outcome": "complete", "processing": False, "count": 29},
        {"outcome": "complete", "processing": False, "error": True, "count": 30},
    ],
)
async def test_mismatched_or_inconsistent_progress_cannot_report_success(scope, changes):
    scope[0].bridge.call.return_value = state(**changes)
    with pytest.raises(ValueError):
        await wait(scope)
    assert scope[0].bridge.call.await_count == 1


@pytest.mark.asyncio
async def test_check_count_bound_keeps_processing_not_success(scope, monkeypatch):
    monkeypatch.setattr(finalization, "MAX_STATE_CHECKS", 3)
    scope[0].bridge.call.return_value = state(count=30)
    result = await wait(scope)
    assert result["outcome"] == "active" and result["processing"]
    assert scope[0].bridge.call.await_count == 3


@pytest.mark.asyncio
async def test_wall_clock_timeout_interrupts_only_status_read(scope, monkeypatch):
    monkeypatch.setattr(finalization, "FINAL_WAIT_SECONDS", 0.01)
    entered = asyncio.Event()

    async def blocked(*args):
        entered.set()
        await asyncio.Event().wait()

    scope[0].bridge.call.side_effect = blocked
    original = state()
    assert await wait(scope, original) is original
    assert entered.is_set()
    assert scope[0].bridge.call.await_count == 1


@pytest.mark.asyncio
async def test_bridge_error_is_not_retried(scope):
    scope[0].bridge.call.side_effect = BridgeError("unavailable")
    with pytest.raises(BridgeError):
        await wait(scope)
    assert scope[0].bridge.call.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidation", ["frame", "closing", "consent", "expiry", "removed"])
async def test_scope_invalidated_during_read_cannot_announce_success(scope, invalidation):
    controller, flow, frame = scope

    async def invalidate(*args):
        if invalidation == "frame":
            frame.valid = False
        elif invalidation == "closing":
            controller.closing = True
        elif invalidation == "consent":
            flow.must_reconsent = True
        elif invalidation == "expiry":
            flow.expires = 0
        else:
            controller.flows.clear()
        return state(count=30, processing=False, outcome="complete")

    controller.bridge.call.side_effect = invalidate
    with pytest.raises(ValueError):
        await wait(scope)
    assert controller.bridge.call.await_count == 1


@pytest.mark.asyncio
async def test_turn_cancellation_propagates_without_retry(scope):
    scope[0].bridge.call.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await wait(scope)
    assert scope[0].bridge.call.await_count == 1
