"""Versioned encrypted companion messages; keep the paired copy identical."""

import json
import re

MAX_WIRE_BYTES = 600000
MESSAGE_TTL = 30


class BridgeError(Exception):
    """A safe, non-sensitive transport/protocol failure."""


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None


def seal(key, kind, boot, request_id, data):
    from cryptography.fernet import Fernet
    message = {"v": 1, "kind": kind, "boot": boot, "request_id": request_id, "data": data}
    return Fernet(key).encrypt(json.dumps(message, separators=(",", ":")).encode())


def open_message(key, token, kind, boot):
    from cryptography.fernet import Fernet, InvalidToken
    try:
        if not isinstance(token, bytes) or len(token) > MAX_WIRE_BYTES:
            raise ValueError
        message = json.loads(Fernet(key).decrypt(token, ttl=MESSAGE_TTL))
        if (not isinstance(message, dict) or set(message) != {"v", "kind", "boot", "request_id", "data"}
                or type(message["v"]) is not int or message["v"] != 1
                or message["kind"] != kind or message["boot"] != boot
                or not identifier(boot) or not identifier(message["request_id"])
                or not isinstance(message["data"], dict)):
            raise ValueError
        return message["request_id"], message["data"]
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        raise BridgeError("Learning bridge authentication failed") from None
