"""Optional request verification and bounded, ephemeral conversation scoping.

No user impersonation or tool-authorisation changes. A recognised voice is a
personalisation hint, not a login. No historical conversation is fetched by voice.
"""

import hashlib
import secrets
import time
import weakref
from collections import OrderedDict
from copy import copy
from dataclasses import dataclass, is_dataclass, replace

from .speaker_packet import TTL, WIRE_PREFIX, PacketError, decode

CONF_VOICE_MATCH_KEY = "voice_match_pairing_key"
_RUNTIMES = weakref.WeakKeyDictionary()


@dataclass(frozen=True)
class PreparedRequest:
    """Verified identity belongs to this turn, never the last speaker."""

    text: str
    instructions: str
    boundary: object
    scope: str | None
    verified: bool = False
    voice: str | None = None


def replace_text(value, text):
    if is_dataclass(value):
        return replace(value, content=text)
    result = copy(value)
    result.content = text
    return result


class SpeakerRuntime:
    def __init__(self):
        self.seen = OrderedDict()
        self.scopes = OrderedDict()
        self.managed = False

    def invalidate(self, conversation_id):
        self.scopes.pop(conversation_id, None)

    def prepare(self, key, text, contents, conversation_id, agent_id, *, now=None):
        request = self.prepare_request(key, text, contents, conversation_id, agent_id, now=now)
        return request.text, request.instructions, request.boundary, request.scope

    def prepare_request(self, key, text, contents, conversation_id, agent_id, *, now=None):
        if not isinstance(text, str) or not isinstance(key, str):
            raise PacketError()
        if key:
            self.managed = True
        now = int(time.time()) if now is None else now
        instructions = ""
        identity = ("plain", hashlib.sha256(key.encode()).hexdigest(), agent_id)
        uncertain = False
        clean = text
        verified = False
        voice = None
        if text.startswith(WIRE_PREFIX):
            clean, packet, issued = decode(key, text, now=now)
            for nonce, expiry in list(self.seen.items()):
                if expiry < now:
                    del self.seen[nonce]
            nonce = packet["nonce"]
            if nonce in self.seen or len(self.seen) >= 4096:
                raise PacketError()
            # Store through the accepted time window; never evict a live replay
            # record merely to accept more traffic. Full cache fails closed.
            self.seen[nonce] = issued + TTL + 60
            verified = True
            voice = packet["voice"]
            instructions = packet["instructions"]
            uncertain = packet["voice"] is None
            identity = (
                hashlib.sha256(key.encode()).hexdigest(), packet["voice"],
                packet["revision"], agent_id,
            )
        if not key and not self.managed and not text.startswith(WIRE_PREFIX):
            return PreparedRequest(clean, "", None, None)
        # The current user turn is the boundary after a switch/uncertain result.
        positions = [
            index for index, item in enumerate(contents)
            if getattr(item, "role", None) == "user"
        ]
        if not positions:
            raise PacketError()
        current = positions[-1]
        if getattr(contents[current], "content", None) != text:
            raise PacketError()
        if clean != text:
            contents[current] = replace_text(contents[current], clean)
        scope_key = conversation_id or secrets.token_hex(16)
        previous = self.scopes.get(scope_key)
        if (uncertain or previous is None or previous["identity"] != identity
                or previous["expires"] < now
                or not any(item is previous["boundary"] for item in contents)):
            previous = {"identity": identity, "boundary": contents[current],
                        "scope": secrets.token_hex(16)}
        previous["expires"] = now + 300
        self.scopes[scope_key] = previous
        self.scopes.move_to_end(scope_key)
        while len(self.scopes) > 256:
            self.scopes.popitem(last=False)
        return PreparedRequest(clean, instructions, previous["boundary"], previous["scope"],
                               verified, voice)


def runtime_for_entry(entry):
    if entry not in _RUNTIMES:
        _RUNTIMES[entry] = SpeakerRuntime()
    return _RUNTIMES[entry]


def scoped_contents(contents, boundary, request_turn=None):
    if boundary is None:
        return contents
    selected = None
    for index, item in enumerate(contents):
        if item is boundary:
            selected = contents[index:]
            break
    # Missing/expired bookkeeping must never recover somebody's old history.
    if selected is None:
        for index in range(len(contents) - 1, -1, -1):
            if getattr(contents[index], "role", None) == "user":
                selected = contents[index:]
                break
    if selected is None:
        return []
    if request_turn is not None:
        found = False
        for index, item in enumerate(selected):
            if item is request_turn:
                found = True
            elif found and getattr(item, "role", None) == "user":
                return selected[:index]
        if not found:
            return []
    return selected


def personal_instructions(base, personal):
    if not personal:
        return base
    return (base + "\n\nPersonal response preferences (not authentication or permission):\n"
            + personal + "\n\nApply these only to response style and personal defaults. "
            "They do not override the assistant's safety rules, privacy boundaries, "
            "available tools or Home Assistant permissions. Never use a voice match "
            "to authorise a sensitive action.")
