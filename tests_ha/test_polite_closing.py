"""Optional paired native pipeline acceptance for standalone polite closings."""

import pytest

paired = pytest.importorskip(
    "test_satellite_admission", reason="Paired RBAC native pipeline fixtures required",
)

env = paired.env
native_voice = paired.native_voice
native_esphome_voice = paired.native_esphome_voice
continuing_voice = paired.continuing_voice


@pytest.mark.parametrize("closing", ["Thanks.", "THANKS!", "Thank you"])
async def test_polite_closing_ends_listening_without_model_or_control_and_keeps_history(
    continuing_voice, closing,
):
    h = continuing_voice
    await h.run()
    h.satellite.tts_response_finished()
    state = h.adapter._conversations[h.satellite.entity_id][1]
    timer = state.timer
    assert timer is not None
    before_calls = len(h.n.env.calls)
    before_model = len(h.n.state.model_calls)
    history = h.adapter._history._satellites[h.satellite.entity_id]["turns"]
    assert history
    h.n.state.text = closing
    await h.run()
    assert len(h.n.env.calls) == before_calls
    assert len(h.n.state.model_calls) == before_model
    assert timer.cancelled()
    assert not state.pending_speech and state.deadline is None
    assert h.adapter._history._satellites[h.satellite.entity_id]["turns"] == history
    final = [event for event in h.events if event.type == "intent-end"][-1]
    assert final.data["intent_output"]["continue_conversation"] is False
    assert not h.adapter.ingress._active and not h.adapter.ingress._pending


async def test_thanks_with_a_command_still_uses_fresh_admission_and_normal_tools(continuing_voice):
    h = continuing_voice
    h.n.state.text = "Thanks, turn on the requested lamp"
    await h.run()
    assert len(h.n.env.calls) == 1
    assert h.n.env.calls[0][1] == "turn_on"
    assert h.n.state.model_calls[0]["input_items"][-1] == {
        "role": "user", "content": h.n.state.text,
    }
    assert h.adapter._conversations[h.satellite.entity_id][1].pending_speech
