"""Exact-task, one-use phone clips and bounded in-memory cleanup."""

import asyncio
import unittest
from types import SimpleNamespace

from custom_components.codex_assist.learning.phone_handoff import PhoneHandoffs


class PhoneHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 100.0
        self.frames = PhoneHandoffs(clock=lambda: self.now)
        self.connection = object()
        self.session = SimpleNamespace(conversation_id="chat")

    async def asyncTearDown(self):
        self.frames.close()

    def reserve(self):
        owner = self.frames.reserve(self.connection, "alice", self.session)
        self.frames.put(owner, b"private-audio", "private-text")
        return owner

    def take(self, **overrides):
        values = {
            "connection": self.connection,
            "user_id": "alice",
            "session": self.session,
            "conversation_id": "chat",
        }
        values.update(overrides)
        return self.frames.take(**values)

    async def test_one_use_and_connection_stays_busy_until_task_finishes(self):
        owner = self.reserve()
        self.assertEqual(self.take().audio, b"private-audio")
        self.assertIsNone(self.take())
        with self.assertRaises(ValueError):
            self.frames.reserve(self.connection, "alice", self.session)
        self.frames.discard(owner)
        self.reserve()

    async def test_copied_task_cannot_take_clip(self):
        self.reserve()
        self.assertIsNone(await asyncio.create_task(self._take_in_child()))
        self.assertIsNotNone(self.take())

    async def _take_in_child(self):
        return self.take()

    async def test_binding_mismatches_destroy_clip(self):
        for override in (
            {"connection": object()},
            {"user_id": "bob"},
            {"session": SimpleNamespace(conversation_id="chat")},
            {"conversation_id": "other-chat"},
        ):
            with self.subTest(override=override):
                owner = self.reserve()
                frame = self.frames.pending[owner].frame
                self.assertIsNone(self.take(**override))
                self.assertEqual((frame.audio, frame.text), (b"", ""))
                self.frames.discard(owner)

    async def test_expiry_cannot_be_consumed(self):
        owner = self.reserve()
        frame = self.frames.pending[owner].frame
        self.now += 60
        self.assertIsNone(self.take())
        self.assertEqual(frame.audio, b"")

    async def test_diagnostics_distinguish_mismatch_expiry_and_missing_without_clip_data(self):
        logger = "custom_components.codex_assist.learning.phone_diagnostics"
        with self.assertLogs(logger, level="INFO") as logs:
            owner = self.reserve()
            self.assertIsNone(self.take(user_id="PRIVATE-other-account"))
            self.frames.discard(owner)
            self.reserve()
            self.now += 60
            self.assertIsNone(self.take())
            self.assertIsNone(self.take())
        output = "\n".join(logs.output)
        for result in ("binding_mismatch", "expired", "missing"):
            self.assertIn(f"result={result}", output)
        for private in ("PRIVATE", "private-audio", "private-text"):
            self.assertNotIn(private, repr([entry.__dict__ for entry in logs.records]))

    async def test_task_completion_and_disconnect_destroy_pending_audio(self):
        owner = self.reserve()
        frame = self.frames.pending[owner].frame
        self.frames.drop_connection(self.connection)
        self.assertEqual(frame.audio, b"")
        self.assertTrue(self.frames.busy)  # Scope remains held until native task completion.
        self.frames.discard(owner)
        self.assertFalse(self.frames.busy)

        async def child():
            task = self.reserve()
            return self.frames.pending[task].frame

        frame = await asyncio.create_task(child())
        await asyncio.sleep(0)
        self.assertEqual(frame.audio, b"")
        self.assertFalse(self.frames.pending)
        self.assertFalse(self.frames.busy)

    async def test_capacity_and_close(self):
        ready = asyncio.Queue()
        release = asyncio.Event()

        async def hold():
            self.frames.reserve(object(), "alice", self.session)
            await ready.put(True)
            await release.wait()

        tasks = [asyncio.create_task(hold()) for _ in range(8)]
        try:
            for _ in tasks:
                await ready.get()
            with self.assertRaises(ValueError):
                self.frames.reserve(object(), "alice", self.session)
            self.frames.close()
            self.assertFalse(self.frames.pending)
            self.assertFalse(self.frames.busy)
            with self.assertRaises(ValueError):
                self.reserve()
        finally:
            release.set()
            await asyncio.gather(*tasks)
