"""Bounded one-turn RAM handoff; marker text is not a recording credential."""

import asyncio
import time
from dataclasses import dataclass

from .phone_diagnostics import record
from .phone_flow import PhoneFrame


@dataclass(repr=False)
class Pending:
    connection: object
    user_id: str
    session: object
    started_at: float
    login_id: str | None = None
    permit: dict | None = None
    frame: PhoneFrame | None = None
    timer: object = None


class PhoneHandoffs:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.pending = {}
        self.busy = {}
        self.scopes = {}
        self.active = {}
        self.closed = False

    def reserve(self, connection, user_id, session, *, login_id=None):
        task = asyncio.current_task()
        scope = (
            (login_id, user_id, session.conversation_id)
            if session is not None and login_id
            else None
        )
        if (
            self.closed
            or task is None
            or session is None
            or len(self.pending) >= 8
            or id(connection) in self.busy
            or task in self.pending
            or (scope is not None and scope in self.scopes)
        ):
            raise ValueError("Phone recording unavailable")
        pending = Pending(connection, user_id, session, self.clock(), login_id=login_id)
        self.pending[task] = pending
        self.busy[id(connection)] = task
        if scope is not None:
            self.scopes[scope] = task
        pending.timer = asyncio.get_running_loop().call_later(60, self.discard, task)
        task.add_done_callback(self.discard)
        return task

    def set_permit(self, owner, permit):
        pending = self.pending.get(owner)
        if pending is None:
            raise ValueError("Recording expired")
        pending.permit = permit

    def put(self, owner, audio, text):
        pending = self.pending.get(owner)
        if pending is None or self.clock() - pending.started_at >= 60:
            raise ValueError("Recording expired")
        pending.frame = PhoneFrame(
            pending.connection,
            pending.user_id,
            pending.session.conversation_id,
            pending.started_at,
            audio,
            text,
            login_id=pending.login_id,
            permit=pending.permit,
        )
        pending.permit = None

    def take(self, connection, user_id, session, conversation_id):
        task = asyncio.current_task()
        pending = self.pending.pop(task, None)
        if pending is None:
            record("handoff", "missing")
            return None
        pending.timer.cancel()
        valid = (
            pending.connection is connection
            and pending.user_id == user_id
            and pending.session is session
            and session is not None
            and session.conversation_id == conversation_id
            and self.clock() - pending.started_at < 60
        )
        if not valid and pending.frame is not None:
            pending.frame.audio, pending.frame.text = b"", ""
            pending.frame.permit, pending.frame.valid = None, False
        if valid and pending.frame is not None:
            self.active[task] = pending.frame
        record(
            "handoff",
            "consumed"
            if valid
            else "expired"
            if self.clock() - pending.started_at >= 60
            else "binding_mismatch",
        )
        # The connection stays reserved until the native pipeline task ends,
        # including its TTS stage. Overlapping phone turns fail closed.
        return pending.frame if valid else None

    def discard(self, task, release=True):
        pending = self.pending.pop(task, None)
        if pending is not None:
            record("handoff", "expired" if self.clock() - pending.started_at >= 60 else "discarded")
            pending.timer.cancel()
            pending.permit = None
            if pending.frame is not None:
                pending.frame.audio, pending.frame.text = b"", ""
                pending.frame.permit, pending.frame.valid = None, False
        frame = self.active.pop(task, None)
        if frame is not None:
            frame.audio, frame.text = b"", ""
            frame.permit, frame.valid = None, False
        if not release:
            return
        for connection, owner in list(self.busy.items()):
            if owner is task:
                self.busy.pop(connection, None)
        for scope, owner in list(self.scopes.items()):
            if owner is task:
                self.scopes.pop(scope, None)

    def drop_connection(self, connection):
        owner = self.busy.get(id(connection))
        if owner is not None:
            # Keep the scope busy until its cancelled native task actually ends.
            self.discard(owner, release=False)

    def close(self):
        self.closed = True
        for owner in set(self.pending) | set(self.active):
            self.discard(owner)
        self.busy.clear()
        self.scopes.clear()
