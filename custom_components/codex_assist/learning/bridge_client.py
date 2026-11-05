"""Authenticated bridge client. No Ingress cookies, forwarded identity or retries."""

import asyncio
import uuid
from urllib.parse import urlsplit

from .learning_bridge_protocol import (
    MAX_WIRE_BYTES,
    BridgeError,
    identifier,
    open_message,
    seal,
)


def validate_url(value):
    try:
        if not isinstance(value, str) or any(ord(character) < 33 for character in value):
            raise ValueError
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError
        _ = url.port  # Reject malformed/out-of-range ports as well.
    except ValueError, TypeError, AttributeError:
        raise ValueError(
            "Use the add-on's internal HTTP(S) origin, without credentials or a path"
        ) from None
    return value.rstrip("/")


class BridgeClient:
    def __init__(self, url, key, session):
        self.url = validate_url(url)
        self._key = key
        self._session = session

    async def _read(self, response):
        if response.status != 200:
            raise BridgeError("Learning bridge unavailable")
        data = bytearray()
        async for chunk in response.content.iter_chunked(8192):
            if len(data) + len(chunk) > MAX_WIRE_BYTES:
                raise BridgeError("Learning bridge response too large")
            data.extend(chunk)
        return bytes(data)

    async def call(self, operation, user_id, data):
        # Each call is a new request; a timed-out mutation is never retried.
        from aiohttp import ClientError

        try:
            async with asyncio.timeout(20):
                async with self._session.get(
                    self.url + "/api/learning/bridge/challenge", allow_redirects=False
                ) as response:
                    import json

                    challenge = json.loads(await self._read(response))
                boot = challenge.get("boot") if isinstance(challenge, dict) else None
                if not identifier(boot):
                    raise BridgeError("Learning bridge unavailable")
                request_id = uuid.uuid4().hex
                wire = seal(
                    self._key,
                    "request",
                    boot,
                    request_id,
                    {"op": operation, "user_id": user_id, "data": data},
                )
                if len(wire) > MAX_WIRE_BYTES:
                    raise BridgeError("Learning bridge request too large")
                async with self._session.post(
                    self.url + "/api/learning/bridge/exchange",
                    data=wire,
                    headers={"Content-Type": "application/octet-stream"},
                    allow_redirects=False,
                ) as response:
                    reply_id, answer = open_message(
                        self._key, await self._read(response), "response", boot
                    )
                if (
                    reply_id != request_id
                    or answer.get("ok") is not True
                    or not isinstance(answer.get("result"), dict)
                ):
                    raise BridgeError("Learning bridge request denied or needs attention")
                return answer["result"]
        except ClientError, TimeoutError, ValueError, TypeError:
            # Do not include URLs, request bodies, credentials or peer error text.
            raise BridgeError(
                "Learning bridge outcome unverified; do not retry automatically"
            ) from None
