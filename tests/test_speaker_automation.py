"""Request-bound speaker conditions, without HA or a live model."""

import asyncio
from collections import UserDict
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from custom_components.codex_assist.speaker_automation import SpeakerAutomations
from custom_components.codex_assist.speaker_packet import encode
from custom_components.codex_assist.voice_match import SpeakerRuntime


def prepared(voice="alice", text="Good morning!"):
    key = Fernet.generate_key().decode()
    wire = encode(key, text, voice=voice, revision="a" * 32 if voice else None)
    return SpeakerRuntime().prepare_request(
        key, wire, [SimpleNamespace(role="user", content=wire)], "chat", "agent"
    )


@pytest.mark.asyncio
async def test_one_identity_reused_across_phrases_and_not_from_trace_copies():
    bridge = SpeakerAutomations()
    captured = []

    async def run(metadata):
        captured.append(metadata)
        assert bridge.speaker_is({"trigger": {"voice_match": metadata}}, "alice")
        assert bridge.speaker_is(UserDict({"trigger": {"voice_match": metadata}}), "alice")
        assert not bridge.speaker_is({"trigger": {"voice_match": dict(metadata)}}, "alice")
        assert not bridge.speaker_is({"trigger": {"voice_match": metadata}}, "bob")
        metadata["voice"] = "bob"
        assert bridge.speaker_is({"trigger": {"voice_match": metadata}}, "alice")
        assert not bridge.speaker_is({"trigger": {"voice_match": metadata}}, "bob")
        return "Personal response"

    bridge.subscribe(["good morning", "good evening"], run)
    for text in ("Good morning!", "GOOD EVENING."):
        result = await bridge.dispatch(prepared(text=text))
        assert result.matched and result.response == "Personal response"
    assert not bridge.speaker_is({"trigger": {"voice_match": captured[0]}}, "alice")


@pytest.mark.asyncio
async def test_unknown_manual_unpaired_and_forged_variables_cannot_select_person():
    bridge = SpeakerAutomations()
    calls = []

    async def run(metadata):
        calls.append(metadata)
        assert not bridge.speaker_is({"trigger": {"voice_match": metadata}}, "alice")

    bridge.subscribe(["good morning"], run)
    assert (await bridge.dispatch(prepared(None))).matched
    plain = SpeakerRuntime().prepare_request(
        "", "good morning", [SimpleNamespace(role="user", content="good morning")], None, "agent"
    )
    assert not (await bridge.dispatch(plain)).matched
    assert len(calls) == 1
    for variables in (None, {}, {"trigger": "manual"},
                      {"trigger": {"voice_match": {"voice": "alice"}}}):
        assert not bridge.speaker_is(variables, "alice")


@pytest.mark.asyncio
async def test_concurrent_devices_keep_their_own_speaker_and_cleanup():
    bridge = SpeakerAutomations()
    ready = asyncio.Event()
    count = 0

    async def run(metadata):
        nonlocal count
        count += 1
        if count == 2:
            ready.set()
        await ready.wait()
        await asyncio.sleep(0)
        variables = {"trigger": {"voice_match": metadata}}
        assert bridge.speaker_is(variables, metadata["voice"])
        assert not bridge.speaker_is(variables, "bob" if metadata["voice"] == "alice" else "alice")
        return metadata["voice"]

    bridge.subscribe(["good morning"], run)
    results = await asyncio.gather(bridge.dispatch(prepared("alice")),
                                   bridge.dispatch(prepared("bob")))
    assert [item.response for item in results] == ["alice", "bob"]
    assert not bridge.active


@pytest.mark.asyncio
async def test_cancel_failure_unsubscribe_and_capacity_fail_closed():
    bridge = SpeakerAutomations()

    async def fail(metadata):
        assert bridge.speaker_is({"trigger": {"voice_match": metadata}}, "alice")
        raise RuntimeError("synthetic failure")

    remove = bridge.subscribe(["good morning"], fail)
    with pytest.raises(RuntimeError):
        await bridge.dispatch(prepared())
    assert not bridge.active
    remove()
    remove()
    assert not (await bridge.dispatch(prepared())).matched

    started = asyncio.Event()

    async def wait(metadata):
        started.set()
        await asyncio.Event().wait()

    bridge.subscribe(["good morning"], wait)
    task = asyncio.create_task(bridge.dispatch(prepared()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not bridge.active
    bridge.max_active = 0
    with pytest.raises(RuntimeError):
        await bridge.dispatch(prepared())


@pytest.mark.asyncio
async def test_literal_sentences_do_not_match_arbitrary_substrings():
    bridge = SpeakerAutomations()
    bridge.subscribe(["good morning"], lambda _: None)
    assert not (await bridge.dispatch(prepared(text="do not say good morning"))).matched


def test_preparation_returns_verified_identity_without_personal_instructions_in_metadata():
    request = prepared()
    assert request.verified and request.voice == "alice"
    key = Fernet.generate_key().decode()
    wire = encode(key, "hello", voice="bob", revision="b" * 32)
    runtime = SpeakerRuntime()
    request = runtime.prepare_request(key, wire, [SimpleNamespace(role="user", content=wire)],
                                      None, "agent")
    assert request.voice == "bob"
    from custom_components.codex_assist.speaker_packet import PacketError

    with pytest.raises(PacketError):
        runtime.prepare_request(key, wire, [SimpleNamespace(role="user", content=wire)],
                                None, "agent")
