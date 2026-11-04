"""Experimental object-bound STT handoff: never correlate by transcript value."""

import asyncio
import copy
import json

import pytest
from cryptography.fernet import Fernet

from custom_components.codex_assist.speaker_handoff import RequestHandoffs, SpeakerTranscript
from custom_components.codex_assist.speaker_packet import PacketError, encode


def packet(key, voice="alice", now=None):
    return encode(key, "hello", voice=voice, revision="a" * 32 if voice else None,
                  instructions="Private preference" if voice else "", now=now)


@pytest.mark.asyncio
async def test_clean_serialization_and_single_use_identity():
    handoffs = RequestHandoffs()
    key = Fernet.generate_key().decode()
    wire = packet(key)
    text = handoffs.issue(key, wire)
    assert type(text) is SpeakerTranscript
    assert str(text) == "hello" and repr(text) == "'hello'"
    assert json.dumps({"text": text}) == '{"text": "hello"}'
    assert "Private preference" not in repr(text)
    assert wire not in json.dumps({"text": text})
    assert handoffs.consume(key, text) == wire
    assert not handoffs.pending
    with pytest.raises(PacketError):
        handoffs.consume(key, text)


@pytest.mark.asyncio
async def test_identical_words_have_different_request_associations():
    handoffs = RequestHandoffs()
    key = Fernet.generate_key().decode()
    alice_wire, bob_wire = packet(key), packet(key, "bob")
    alice, bob = handoffs.issue(key, alice_wire), handoffs.issue(key, bob_wire)
    assert alice == bob and alice is not bob
    assert len(handoffs.pending) == 2
    assert handoffs.consume(key, bob) == bob_wire
    assert handoffs.consume(key, alice) == alice_wire


@pytest.mark.asyncio
async def test_copy_json_and_forged_carriers_cannot_borrow_identity():
    handoffs = RequestHandoffs()
    key = Fernet.generate_key().decode()
    text = handoffs.issue(key, packet(key))
    for other in (SpeakerTranscript("hello"), copy.copy(text), copy.deepcopy(text)):
        with pytest.raises(PacketError):
            handoffs.consume(key, other)
    # Serialization intentionally loses context, never looks up matching words.
    plain = json.loads(json.dumps(text))
    assert handoffs.consume(key, plain) is None
    assert handoffs.consume(key, text)


@pytest.mark.asyncio
async def test_wrong_task_entry_key_expiry_and_capacity_fail_closed():
    handoffs = RequestHandoffs()
    key = Fernet.generate_key().decode()
    text = handoffs.issue(key, packet(key))

    async def wrong_task():
        with pytest.raises(PacketError):
            handoffs.consume(key, text)

    await asyncio.create_task(wrong_task())
    # A wrong task must not consume the rightful owner's record.
    assert handoffs.consume(key, text)
    text = handoffs.issue(key, packet(key))
    with pytest.raises(PacketError):
        RequestHandoffs().consume(key, text)
    with pytest.raises(PacketError):
        handoffs.consume(Fernet.generate_key().decode(), text)
    text = handoffs.issue(key, packet(key, now=1000), now=1000)
    with pytest.raises(PacketError):
        handoffs.consume(key, text, now=1201)
    assert not handoffs.pending
    handoffs.max_pending = 0
    with pytest.raises(PacketError):
        handoffs.issue(key, packet(key))


@pytest.mark.asyncio
async def test_owner_cancellation_cleans_up_even_if_trace_retains_text():
    handoffs = RequestHandoffs()
    key = Fernet.generate_key().decode()
    retained = []
    ready = asyncio.Event()

    async def owner():
        retained.append(handoffs.issue(key, packet(key)))
        ready.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(owner())
    await ready.wait()
    assert handoffs.pending
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    assert retained[0] == "hello" and not handoffs.pending
