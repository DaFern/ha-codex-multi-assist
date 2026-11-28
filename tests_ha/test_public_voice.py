"""Paired finite public replies never grant device or conversation access."""

from datetime import UTC, datetime

import pytest
from homeassistant.util import dt as dt_util

from custom_components.codex_assist.protected_conversation import public_voice_reply

paired = pytest.importorskip("test_satellite_admission")
env = paired.env
native_voice = paired.native_voice
native_esphome_voice = paired.native_esphome_voice


@pytest.mark.parametrize("zone,instant,expected", [
    ("Europe/London", datetime(2026, 11, 28, 0, 5, tzinfo=UTC), "It's 12:05 am."),
    ("Europe/London", datetime(2026, 7, 28, 11, 0, tzinfo=UTC), "It's 12:00 pm."),
    ("America/New_York", datetime(2026, 11, 28, 1, 5, tzinfo=UTC), "It's 8:05 pm."),
])
def test_clock_uses_configured_timezone_including_dst(monkeypatch, zone, instant, expected):
    monkeypatch.setattr(dt_util, "utcnow", lambda: instant)
    assert public_voice_reply("Could you please tell me what time it is right now?", zone) == (
        "time", expected,
    )


@pytest.mark.parametrize("text", [
    "Thanks, turn on the lights", "What time is it and unlock the door",
    "Tell me the time my alarm is set for", "What is my work calendar",
    "Forget this conversation", "Stop the music", "What time does the office close",
])
def test_public_reply_never_matches_compound_or_private_requests(text):
    assert public_voice_reply(text, "Europe/London") is None


@pytest.mark.parametrize("speaker", [None, "child", "owner"])
@pytest.mark.parametrize("text,reply", [
    ("Thank you", "You're welcome."), ("Thanks!", "You're welcome."),
    ("Stop listening", "Okay."), ("What time is it?", "It's 12:05 am."),
])
async def test_public_reply_with_no_device_or_guest_access(
    native_esphome_voice, monkeypatch, speaker, text, reply,
):
    h = native_esphome_voice
    h.n.state.speaker, h.n.state.text = speaker, text
    monkeypatch.setattr(
        dt_util, "utcnow", lambda: datetime(2026, 11, 28, 0, 5, tzinfo=UTC),
    )
    monkeypatch.setattr(h.adapter.hass.config, "time_zone", "Europe/London")
    provider = h.adapter.ingress._provider
    monkeypatch.setattr(provider, "_guest_role_provider", lambda: None)
    monkeypatch.setattr(provider, "_candidates", ())
    await h.run()
    assert h.n.state.tts == [reply]
    assert h.n.env.calls == [] and h.n.state.model_calls == []
    assert not h.adapter._history._satellites.get(h.satellite.entity_id, {}).get("turns")
    state = h.adapter._conversations[h.satellite.entity_id][1]
    assert state.pending_speech is (text == "What time is it?")
    assert not h.adapter.ingress._active and not h.adapter.ingress._pending


@pytest.mark.parametrize("change", ["forged", "plaintext", "disconnect"])
async def test_public_reply_retains_packet_and_transport_checks(native_esphome_voice, change):
    h = native_esphome_voice
    h.n.state.text = "Thank you"
    if change == "forged":
        h.n.state.forged = True
    elif change == "plaintext":
        h.client.clear_noise_psk()
    else:
        h.runtime.async_on_disconnect()
    await h.run()
    assert "You're welcome." not in h.n.state.tts
    assert h.n.env.calls == [] and h.n.state.model_calls == []
