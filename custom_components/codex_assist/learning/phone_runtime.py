"""Phone-only runtime; no device-ID or accountless-satellite fallback."""

import asyncio
import time

from homeassistant.auth.models import TOKEN_TYPE_NORMAL
from homeassistant.components.websocket_api.connection import ActiveConnection

from .phone_diagnostics import record
from .phone_flow import PhoneController
from .phone_handoff import PhoneHandoffs


class PhoneRuntime:
    def __init__(self, hass, entry, bridge, source_id):
        self.hass, self.entry, self.source_id = hass, entry, source_id
        self.controller = PhoneController(bridge, authorize=self.authorize)
        self.frames = PhoneHandoffs()
        self.connections = {}
        self.cleanup_tasks = set()
        self.completed = set()

    def authorize(self, connection, user_id):
        """Return only the server-authenticated, still-valid login identity."""
        if not isinstance(connection, ActiveConnection) or connection.hass is not self.hass:
            raise ValueError("Authenticated phone login required")
        login_id = connection.refresh_token_id
        if not isinstance(login_id, str) or not login_id:
            raise ValueError("Authenticated phone login required")
        login = self.hass.auth.async_get_refresh_token(login_id)
        if (
            login is None
            or login.token_type != TOKEN_TYPE_NORMAL
            or login.user.id != user_id
            or connection.user.id != user_id
            or not login.user.is_active
            or login.user.system_generated
            or (login.expire_at is not None and login.expire_at <= time.time())
        ):
            raise ValueError("Authenticated phone login unavailable")
        return login_id

    def complete(self, frame):
        if (
            not frame.valid
            or id(frame.connection) not in self.connections
            or self.authorize(frame.connection, frame.user_id) != frame.login_id
        ):
            raise ValueError("Phone turn interrupted")
        self.completed.add(id(frame.connection))

    def watch(self, connection):
        if self.controller.closing:
            raise ValueError("Phone learning is stopping")
        self.completed.discard(id(connection))
        if id(connection) in self.connections:
            return
        if len(self.connections) >= 32:
            raise ValueError("Too many phone connections")
        key = ("codex_assist_voice_learning_phone", self.entry.entry_id)
        self.connections[id(connection)] = (connection, key)

        def disconnect():
            record("connection", "disconnect")
            self.connections.pop(id(connection), None)
            completed = id(connection) in self.completed
            self.completed.discard(id(connection))
            self.controller.connection_lost(connection, completed=completed)
            self.frames.drop_connection(connection)  # Drop raw audio synchronously.
            if not self.hass.is_stopping:
                task = self.hass.async_create_background_task(
                    self.controller.disconnect(connection), "phone_voice_learning_disconnect"
                )
                self.cleanup_tasks.add(task)
                task.add_done_callback(self.cleanup_tasks.discard)

        connection.subscriptions[key] = disconnect

    async def shutdown(self):
        ready = await self.controller.shutdown()
        if self.cleanup_tasks:
            await asyncio.gather(*list(self.cleanup_tasks), return_exceptions=True)
        if ready:
            self.frames.close()
            for connection, key in self.connections.values():
                connection.subscriptions.pop(key, None)
            self.connections.clear()
            self.completed.clear()
        return ready
