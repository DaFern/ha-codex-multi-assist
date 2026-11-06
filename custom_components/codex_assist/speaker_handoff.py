"""Experimental in-process STT handoff; not a documented HA metadata API.

Only clean text is serializable. A private registry binds the encrypted packet
to the exact string object, owning task, entry runtime and pairing-key revision.
Never use string equality, transcript hashes or a shared latest-speaker lookup.
"""

import asyncio
import hashlib
import time
import weakref
from dataclasses import dataclass

from .speaker_packet import TTL, PacketError, decode


class SpeakerTranscript(str):
    """Ordinary visible text, with no packet, key or profile attributes."""

    __slots__ = ("__weakref__",)


@dataclass(repr=False)
class _Pending:
    carrier: object
    owner: object
    wire: str
    key_digest: bytes
    expires: float
    cleanup: object = None
    timer: object = None


class RequestHandoffs:
    """One instance per Codex entry runtime. Pending records are bounded/volatile."""

    max_pending = 256

    def __init__(self):
        self.pending = {}

    def clear(self):
        """Remove timers/callbacks as well as packets when an entry stops."""
        for record in list(self.pending.values()):
            record.cleanup()

    def issue(self, key, wire, *, now=None):
        clean, _packet, issued = decode(key, wire, now=now)
        loop = asyncio.get_running_loop()
        owner = asyncio.current_task()
        if owner is None:
            raise PacketError()
        if owner.cancelling():
            raise asyncio.CancelledError()
        for record in list(self.pending.values()):
            if record.expires <= loop.time():
                record.cleanup()
        if len(self.pending) >= self.max_pending:
            raise PacketError()
        text = SpeakerTranscript(clean)
        identifier = id(text)
        remaining = max(0, issued + TTL + 60 - (time.time() if now is None else now))
        record = _Pending(None, weakref.ref(owner), wire,
                          hashlib.sha256(key.encode()).digest(), loop.time() + remaining)

        def cleanup(_event=None):
            if self.pending.get(identifier) is not record:
                return
            del self.pending[identifier]
            if record.timer is not None:
                record.timer.cancel()
            if (task := record.owner()) is not None:
                task.remove_done_callback(cleanup)

        record.carrier = weakref.ref(text, cleanup)
        record.cleanup = cleanup
        self.pending[identifier] = record
        record.timer = loop.call_later(remaining, cleanup)
        owner.add_done_callback(cleanup)
        return text

    def consume(self, key, text, *, now=None):
        if not isinstance(text, SpeakerTranscript):
            # Plain/serialized text has no identity. Do not guess a matching one.
            return None
        record = self.pending.get(id(text))
        if (record is None or record.carrier() is not text
                or record.owner() is not asyncio.current_task()):
            raise PacketError()
        try:
            if asyncio.current_task().cancelling():
                raise asyncio.CancelledError()
            if not isinstance(key, str):
                raise PacketError()
            if record.key_digest != hashlib.sha256(key.encode()).digest():
                raise PacketError()
            clean, _packet, _issued = decode(key, record.wire, now=now)
            if clean != text:
                raise PacketError()
            return record.wire
        finally:
            record.cleanup()
