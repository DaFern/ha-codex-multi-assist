"""Versioned encrypted request context; never an authentication credential.

Keep in sync with codex_assist/speaker_packet.py. Uses Fernet authenticated
encryption so preferences are not plaintext in STT transcripts/traces.
"""

import hashlib
import json
import re
import uuid

PREFIX = "[[voice-match:v1:"
WIRE_PREFIX = "[[voice-match:"
TTL = 120
MAX_TOKEN = 16384
MAX_TEXT = 16384


def diagnostic_tag(wire):
    """Correlate a request using ciphertext only; never log the token or words.

    A tag is not proof of validation or speaker identity. Encryption randomness
    makes it request-specific rather than a persistent person identifier.
    """
    if (not isinstance(wire, str) or not wire.startswith(PREFIX)
            or len(wire) > MAX_TOKEN + MAX_TEXT + 64):
        return None
    header, separator, _command = wire.partition("]]\n")
    if not separator or not len(PREFIX) < len(header) <= len(PREFIX) + MAX_TOKEN:
        return None
    try:
        encoded = header.encode("ascii")
    except UnicodeError:
        return None
    return hashlib.sha256(encoded).hexdigest()[:16]


class PacketError(ValueError):
    def __init__(self):
        super().__init__("Voice Match pairing or request verification failed")


def valid_key(key):
    try:
        from cryptography.fernet import Fernet
        if not isinstance(key, str) or len(key) != 44:
            return False
        Fernet(key.encode("ascii"))
        return True
    except (ValueError, UnicodeError):
        return False


def encode(key, text, *, voice=None, revision=None, instructions="", now=None):
    from cryptography.fernet import Fernet
    if not valid_key(key) or not isinstance(text, str) or not 1 <= len(text) <= MAX_TEXT:
        raise PacketError()
    payload = {"v": 1, "nonce": uuid.uuid4().hex, "voice": voice,
               "revision": revision, "instructions": instructions,
               "text_hash": hashlib.sha256(text.encode()).hexdigest()}
    validate_payload(payload)
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    cipher = Fernet(key.encode())
    token = (cipher.encrypt(raw) if now is None else cipher.encrypt_at_time(raw, now)).decode()
    if len(token) > MAX_TOKEN:
        raise PacketError()
    return f"{PREFIX}{token}]]\n{text}"


def validate_payload(value):
    if not isinstance(value, dict) or value.get("v") != 1:
        raise PacketError()
    if not isinstance(value.get("nonce"), str) or not re.fullmatch(r"[0-9a-f]{32}", value["nonce"]):
        raise PacketError()
    if (not isinstance(value.get("text_hash"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["text_hash"])):
        raise PacketError()
    instructions = value.get("instructions")
    if not isinstance(instructions, str) or len(instructions) > 2000 or "\x00" in instructions:
        raise PacketError()
    if value.get("voice") is None:
        if value.get("revision") is not None or instructions:
            raise PacketError()
    elif (not isinstance(value["voice"], str)
          or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", value["voice"])
          or not isinstance(value.get("revision"), str)
          or not re.fullmatch(r"[0-9a-f]{32}", value["revision"])):
        raise PacketError()


def decode(key, text, *, now=None):
    from cryptography.fernet import Fernet, InvalidToken
    if not valid_key(key) or not isinstance(text, str) or len(text) > MAX_TOKEN + MAX_TEXT + 64:
        raise PacketError()
    if not text.startswith(PREFIX) or "]]\n" not in text:
        raise PacketError()
    token, command = text[len(PREFIX):].split("]]\n", 1)
    if not 1 <= len(token) <= MAX_TOKEN or not 1 <= len(command) <= MAX_TEXT:
        raise PacketError()
    try:
        cipher = Fernet(key.encode())
        raw = (cipher.decrypt(token.encode(), ttl=TTL) if now is None
               else cipher.decrypt_at_time(token.encode(), ttl=TTL, current_time=now))
        value = json.loads(raw)
        validate_payload(value)
        if value["text_hash"] != hashlib.sha256(command.encode()).hexdigest():
            raise PacketError()
        issued = cipher.extract_timestamp(token.encode())
        return command, value, issued
    except (InvalidToken, ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise PacketError() from exc
