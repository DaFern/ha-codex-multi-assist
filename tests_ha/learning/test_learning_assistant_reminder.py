"""Native spoken reminders change presentation, never assistant or recording state."""

from unittest.mock import patch

import pytest
import test_phone_learning_pipeline as phone_fixtures

from custom_components.codex_assist.learning import finalization
from custom_components.codex_assist.learning.learning_bridge_protocol import BridgeError

phone = phone_fixtures.phone
pipeline_components = phone_fixtures.pipeline_components
speech = phone_fixtures.speech
REMINDER = (
    "If you're finished with voice learning, remember to switch back to your regular assistant."
)


def assert_reminder(reply):
    assert reply.endswith(REMINDER)
    assert reply.count(REMINDER) == 1


@pytest.mark.parametrize("marker", [4, 12, 13, 15, 16, 17])
async def test_confirmed_stop_appends_reminder_without_uploading_control(phone, marker):
    await phone["run"](1)
    await phone["run"](2)
    await phone["run"](3)
    reply = speech(await phone["run"](marker))
    assert_reminder(reply)
    assert "cancelled" in reply if marker == 12 else "paused" in reply
    assert phone["backend"].count == (0 if marker == 12 else 1)
    assert len([call for call in phone["backend"].calls if call[0] == "sample"]) == 1


async def test_cancel_before_consent_keeps_result_and_appends_reminder(phone):
    assert REMINDER not in speech(await phone["run"](1))
    reply = speech(await phone["run"](12))
    assert "No learning started" in reply
    assert_reminder(reply)
    assert not [
        call for call in phone["backend"].calls if call[0] in {"begin", "discard", "sample"}
    ]


async def test_thirtieth_saved_sample_appends_reminder_only_after_validated_completion(
    phone, monkeypatch
):
    monkeypatch.setattr(finalization, "POLL_INTERVAL", 0)
    original = phone["backend"].call
    final_checks = 0

    async def thirty_samples(operation, user_id, data):
        nonlocal final_checks
        result = await original(operation, user_id, data)
        if operation == "state":
            result.update(
                target=30, outcome="complete" if phone["backend"].count == 30 else "active"
            )
            if phone["backend"].count == 30:
                final_checks += 1
                result.update(
                    processing=final_checks < 3,
                    outcome="active" if final_checks < 3 else "complete",
                )
        return result

    with patch.object(phone["backend"], "call", side_effect=thirty_samples):
        assert REMINDER not in speech(await phone["run"](1))
        assert "Sample 1 of 30" in speech(await phone["run"](2))
        for count in range(1, 31):
            reply = speech(await phone["run"](3))
            assert phone["backend"].count == count
            if count < 30:
                assert f"Sample {count + 1} of 30" in reply
                assert REMINDER not in reply
            else:
                assert "replacement voiceprint validated" in reply
                assert "saved samples were cleaned up" in reply
                assert_reminder(reply)
    assert not phone["runtime"].controller.flows
    assert final_checks == 3, "The final sample waits without another user utterance"
    assert len([call for call in phone["backend"].calls if call[0] == "sample"]) == 30


@pytest.mark.parametrize("marker,operation", [(4, "cancel"), (15, "cancel"), (12, "discard")])
async def test_unverified_stop_keeps_warning_without_confirmed_outcome_reminder(
    phone, marker, operation
):
    await phone["run"](1)
    await phone["run"](2)
    original = phone["backend"].call

    async def uncertain(action, user_id, data):
        if action == operation:
            if action == "discard":
                await original(action, user_id, data)
            raise BridgeError("unavailable")
        result = await original(action, user_id, data)
        if operation == "discard" and action == "state":
            result["outcome"] = "cancelled"
        return result

    with patch.object(phone["backend"], "call", side_effect=uncertain):
        reply = speech(await phone["run"](marker))
        assert REMINDER not in reply
        assert "could not" in reply
        assert phone["backend"].active == (operation != "discard")
        if operation == "discard":
            # Resolve the lost receipt read-only so the fixture can safely unload.
            assert_reminder(speech(await phone["run"](6)))


async def test_cancel_receipt_recovery_appends_reminder_without_retrying_discard(phone):
    await phone["run"](1)
    await phone["run"](2)
    original = phone["backend"].call

    async def lost_receipt(operation, user_id, data):
        if operation == "discard":
            await original(operation, user_id, data)
            raise BridgeError("unavailable")
        result = await original(operation, user_id, data)
        if operation == "state":
            result["outcome"] = "cancelled"
        return result

    with patch.object(phone["backend"], "call", side_effect=lost_receipt):
        assert REMINDER not in speech(await phone["run"](12))
        reply = speech(await phone["run"](6))
    assert "recordings were deleted" in reply
    assert_reminder(reply)
    assert len([call for call in phone["backend"].calls if call[0] == "discard"]) == 1
