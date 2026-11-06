"""Native final turn waits for verified completion without another utterance."""

from unittest.mock import patch

import pytest
import test_phone_learning_pipeline as phone_fixtures

from custom_components.codex_assist.learning import finalization
from custom_components.codex_assist.learning.learning_bridge_protocol import BridgeError

phone = phone_fixtures.phone
pipeline_components = phone_fixtures.pipeline_components
speech = phone_fixtures.speech


@pytest.mark.parametrize(
    "outcome", ["complete", "error", "timeout", "reject", "cancelled", "bridge_error"]
)
async def test_native_final_turn_returns_bounded_verified_result(phone, monkeypatch, outcome):
    monkeypatch.setattr(finalization, "POLL_INTERVAL", 0)
    monkeypatch.setattr(finalization, "MAX_STATE_CHECKS", 3)
    await phone["run"](1)
    await phone["run"](2)
    await phone["run"](3)
    original = phone["backend"].call
    checks = 0
    waiting = False

    async def delayed(operation, user_id, data):
        nonlocal checks, waiting
        result = await original(operation, user_id, data)
        if operation == "sample":
            waiting = True
        if operation == "state" and waiting:
            checks += 1
            result.update(outcome="active", processing=True)
            if checks > 1:
                if outcome == "complete":
                    result.update(outcome="complete", processing=False)
                elif outcome == "error":
                    result.update(error=True, processing=False)
                elif outcome == "reject":
                    phone["backend"].count = 1
                    result.update(count=1, processing=False, notice=True)
                elif outcome == "cancelled":
                    result.update(outcome="cancelled", processing=False)
                elif outcome == "bridge_error":
                    raise BridgeError("synthetic-private-peer-error")
        return result

    with patch.object(phone["backend"], "call", side_effect=delayed):
        reply = speech(await phone["run"](3))
    assert len([call for call in phone["backend"].calls if call[0] == "sample"]) == 2
    assert checks == (4 if outcome == "timeout" else 2)
    if outcome == "complete":
        assert "replacement voiceprint validated" in reply
        assert "saved samples were cleaned up" in reply
        assert "switch back to your regular assistant" in reply
        assert not phone["runtime"].controller.flows
    else:
        assert "Voice learning is complete" not in reply
        if outcome == "timeout":
            assert "This check has ended" in reply and "ask for status" in reply
        elif outcome == "reject":
            assert "Sample not saved. Please try again" in reply
            assert "Sample 2 of 2" in reply
            assert phone["backend"].count == 1
        elif outcome == "error":
            assert "needs attention" in reply
        elif outcome == "cancelled":
            assert "session has ended" in reply
        else:
            assert "could not be verified" in reply
            assert "synthetic-private-peer-error" not in reply


async def test_native_intermediate_processing_does_not_wait_for_finalization(phone, monkeypatch):
    monkeypatch.setattr(finalization, "POLL_INTERVAL", 0)
    await phone["run"](1)
    await phone["run"](2)
    original = phone["backend"].call
    checks = 0

    async def processing(operation, user_id, data):
        nonlocal checks
        result = await original(operation, user_id, data)
        if operation == "state" and phone["backend"].count == 1:
            checks += 1
            result["processing"] = True
        return result

    with patch.object(phone["backend"], "call", side_effect=processing):
        reply = speech(await phone["run"](3))
    assert checks == 1
    assert "This check has ended" in reply
    assert len([call for call in phone["backend"].calls if call[0] == "sample"]) == 1
