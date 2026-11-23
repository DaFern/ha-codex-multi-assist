"""Receipts contain no action evidence and do not require device feedback."""

import asyncio
import json

import pytest

from custom_components.codex_assist import action_receipts
from custom_components.codex_assist.codex_client import (
    CodexTextDelta,
    CodexToolCall,
    CodexToolCallDelta,
)


@pytest.fixture(autouse=True)
def empty_cache():
    action_receipts._RECEIPTS.clear()
    yield
    action_receipts._RECEIPTS.clear()


async def receipt(client, style="Formal butler", model="synthetic"):
    return await action_receipts.async_receipt(client, model=model, instructions=style)


@pytest.mark.asyncio
async def test_cache_is_style_and_model_specific_and_does_not_receive_targets():
    requests = []

    class Client:
        async def stream_turn(self, **kwargs):
            requests.append(kwargs)
            yield CodexTextDelta(json.dumps({"reply": "Certainly, sir."}))

    client = Client()
    assert await receipt(client) == "Certainly, sir."
    assert await receipt(client) == "Certainly, sir."
    assert len(requests) == 1
    assert await receipt(client, style="Friendly assistant") == "Certainly, sir."
    assert await receipt(client, model="another-model") == "Certainly, sir."
    assert len(requests) == 3
    assert requests[0]["tools"] == []
    assert requests[0]["input_items"] == [
        {"role": "user", "content": "Acknowledge that you heard me."},
    ]
    assert all(type(key) is bytes for key in action_receipts._RECEIPTS)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    "", " ", "Command sent.", "I've turned the lamp off.", "Done, sir.",
    "Which device?", "x\n", "one two three four five six seven eight nine", "x" * 121,
])
async def test_status_claims_or_questions_are_not_used_as_receipts(reply):
    class Client:
        async def stream_turn(self, **kwargs):
            yield CodexTextDelta(json.dumps({"reply": reply}))

    assert await receipt(Client()) == "Okay."
    assert not action_receipts._RECEIPTS


@pytest.mark.asyncio
async def test_receipt_timeout_is_bounded_and_does_not_cache_a_generic_fallback(monkeypatch):
    closed = []
    monkeypatch.setattr(action_receipts, "RECEIPT_TIMEOUT", 0.01)

    class Client:
        async def stream_turn(self, **kwargs):
            try:
                await asyncio.Event().wait()
                yield CodexTextDelta('{"reply":"Certainly."}')
            finally:
                closed.append(True)

    assert await asyncio.wait_for(receipt(Client()), 0.1) == "Okay."
    assert closed == [True]
    assert not action_receipts._RECEIPTS


@pytest.mark.asyncio
async def test_no_tool_call_from_receipt_generation_is_dispatched():
    class Client:
        async def stream_turn(self, **kwargs):
            yield CodexToolCallDelta(CodexToolCall("bad", "HassTurnOn", {}))

    assert await receipt(Client()) == "Okay."


@pytest.mark.asyncio
async def test_cancellation_propagates_without_a_spoken_fallback():
    class Client:
        async def stream_turn(self, **kwargs):
            raise asyncio.CancelledError
            yield

    with pytest.raises(asyncio.CancelledError):
        await receipt(Client())
