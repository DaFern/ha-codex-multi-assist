"""Short personality receipts, independent of device state and execution authority."""

import asyncio
import hashlib
import json
import re
from collections import OrderedDict

from .codex_client import CodexResponseItemDelta, CodexTextDelta

MAX_CACHED_STYLES = 64
RECEIPT_TIMEOUT = 2.0
_RECEIPTS = OrderedDict()


async def async_receipt(
    client, *, model, instructions, reasoning_effort="low",
    reasoning_summary="auto", text_verbosity="low",
):
    """Generate once per style/model; retain no device, speaker or outcome data.

    This means 'I heard you', never 'the device responded'. Failed generation
    falls back neutrally rather than hard-coding somebody else's personality.
    """
    key = hashlib.sha256(json.dumps([model, instructions]).encode()).digest()
    if key in _RECEIPTS:
        _RECEIPTS.move_to_end(key)
        return _RECEIPTS[key]
    try:
        async with asyncio.timeout(RECEIPT_TIMEOUT):
            stream = client.stream_turn(
                model=model,
                instructions=(
                    f"{instructions}\n\n"
                    "Write only a very short acknowledgement that you heard a device-control "
                    "request, in the selected personality and user language. For example a "
                    "formal assistant might say 'Certainly, sir.' Use that form of address "
                    "ONLY if this personality calls for it. Do not impose another character. "
                    "This is a receipt, NOT an action or device-status report. Never mention "
                    "devices, sending commands, success, completion, checking, or future work. "
                    "Use at most eight words. No questions, explanations, tools or actions. "
                    "Return JSON with a single string field 'reply'."
                ),
                input_items=[{"role": "user", "content": "Acknowledge that you heard me."}],
                tools=[], reasoning_effort=reasoning_effort,
                reasoning_summary=reasoning_summary, text_verbosity=text_verbosity,
                text_format={"type": "json_schema", "name": "action_receipt", "strict": True,
                             "schema": {
                                 "type": "object", "additionalProperties": False,
                                 "properties": {"reply": {"type": "string"}},
                                 "required": ["reply"],
                             }},
            )
            chunks = []
            try:
                async for delta in stream:
                    if isinstance(delta, CodexResponseItemDelta):
                        continue
                    if not isinstance(delta, CodexTextDelta):
                        return "Okay."
                    chunks.append(delta.text)
                    if sum(map(len, chunks)) > 512:
                        return "Okay."
            finally:
                await stream.aclose()
            result = json.loads("".join(chunks))
            reply = (
                result.get("reply") if type(result) is dict and set(result) == {"reply"} else None
            )
            if (
                type(reply) is not str or not 0 < len(reply) <= 120
                or not reply.isprintable() or len(reply.split()) > 8
                or any(char in reply for char in "?？")
                or re.search(
                    r"\b(?:sent|command|device|done|completed|turned|switched|"
                    r"activated|opened|closed|locked|unlocked|checking|verified|"
                    r"confirmed|successfully|failed)\b", reply, re.I,
                )
            ):
                return "Okay."
            reply = reply.strip()
            if not reply:
                return "Okay."
            _RECEIPTS[key] = reply
            while len(_RECEIPTS) > MAX_CACHED_STYLES:
                _RECEIPTS.popitem(last=False)
            return reply
    except Exception:
        # Never expose model/auth errors or retry an already-admitted command.
        return "Okay."
