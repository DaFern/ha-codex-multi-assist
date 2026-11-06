"""Privacy and unchanged-consent contracts for phone diagnostic categories."""

import time
import unittest

from custom_components.codex_assist.learning.phone_diagnostics import LOGGER, STT_STEPS, record
from custom_components.codex_assist.learning.phone_flow import (
    NOTICE,
    PhoneController,
    PhoneFrame,
    control_category,
)


class DiagnosticsTests(unittest.TestCase):
    def test_classifications_do_not_echo_transcripts(self):
        cases = {
            "Start learning.": "start_learning",
            " NO! ": "stop",
            "pause learning": "stop",
            "check status": "status",
            "No,": "stop",
            "Please cancel learning.": "cancel",
            "“start learning”": "start_learning_punctuation",
            NOTICE: "notice_like",
            "yes": "other",
            "start voice learning": "uncertain_control",
            "learn my voice": "uncertain_control",
            "Continue learning.": "continue_learning",
            "“continue learning”": "continue_learning_punctuation",
            "Privacy details": "privacy",
            "yes please": "other",
            "unrelated private reading phrase": "other",
        }
        for text, category in cases.items():
            with self.subTest(category=category):
                self.assertEqual(control_category(text), category)

    def test_only_allowlisted_fields_and_bounded_duration_can_be_logged(self):
        private = "PRIVATE-transcript-account-chat-session-key-permit"

        class Sensitive:
            def __str__(self):
                raise AssertionError("Must not serialize an object")

        with self.assertLogs(LOGGER, level="INFO") as logs:
            record(
                private,
                private,
                control=private,
                phase=private,
                continuity=private,
                audio_bytes=10**100,
                cancel_stage=private,
            )
            record(
                Sensitive(),
                Sensitive(),
                control=Sensitive(),
                phase=Sensitive(),
                continuity=Sensitive(),
                audio_bytes=Sensitive(),
                cancel_stage=Sensitive(),
            )
            record("stt", "ready", control="stop", audio_bytes=-99)
        self.assertNotIn(private, repr([entry.__dict__ for entry in logs.records]))
        self.assertIn("audio_ms=10000", logs.output[0])
        self.assertIn("stage=unknown result=unknown", logs.output[1])
        self.assertIn("audio_ms=0", logs.output[1])
        self.assertIn("cancel_stage=unknown", logs.output[0])
        self.assertIn("cancel_stage=unknown", logs.output[1])
        self.assertIn("audio_ms=0", logs.output[2])
        for entry in logs.records:
            self.assertIsNone(entry.exc_info)
            self.assertIsNone(entry.stack_info)

    def test_cancellation_stage_only_records_fixed_vocabulary(self):
        for stage in sorted(STT_STEPS):
            with self.subTest(stage=stage), self.assertLogs(LOGGER, level="INFO") as logs:
                record("stt", "cancelled", cancel_stage=stage)
            self.assertIn(f"cancel_stage={stage}", logs.output[0])


class LookupOnlyBridge:
    async def call(self, operation, user_id, data):
        if operation != "own_profile":
            raise AssertionError("Diagnostic tests must never begin learning")
        return {"id": "PRIVATE-profile"}


class FlowDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.phone = PhoneController(LookupOnlyBridge())
        self.connection = object()

    def frame(self, text, *, connection=None, chat="PRIVATE-chat", user="PRIVATE-user"):
        connection = connection or self.connection
        return PhoneFrame(
            connection,
            user,
            chat,
            time.monotonic(),
            b"PRIVATE-audio" * 100,
            text,
            login_id=f"PRIVATE-login-{id(connection)}",
        )

    async def test_no_still_stops_and_no_private_frame_fields_enter_logs(self):
        frame = self.frame("PRIVATE-transcript")
        with self.assertLogs(LOGGER, level="INFO") as logs:
            await self.phone.handle(frame)
            reply = await self.phone.handle(self.frame("no"))
        self.assertIn("No learning started", reply.speech)
        self.assertFalse(self.phone.flows)
        output = "\n".join(logs.output)
        self.assertIn("control=other continuity=new_scope", output)
        self.assertIn("control=stop continuity=same_scope phase=consent", output)
        self.assertIn("result=cancel_before_start", output)
        self.assertNotIn("PRIVATE", repr([entry.__dict__ for entry in logs.records]))

    async def test_punctuation_and_notice_like_categories_do_not_change_consent(self):
        with self.assertLogs(LOGGER, level="INFO") as logs:
            await self.phone.handle(self.frame("start"))
            for text in ("“start learning”", NOTICE):
                reply = await self.phone.handle(self.frame(text))
                self.assertEqual(reply.speech, NOTICE)
        output = "\n".join(logs.output)
        for category in ("start_learning_punctuation", "notice_like"):
            self.assertIn(f"control={category}", output)
        self.assertEqual(sum("result=notice_repeat" in line for line in logs.output), 2)
        self.assertNotIn(NOTICE, output)
        flow = next(iter(self.phone.flows.values()))
        self.assertEqual(flow.phase, "consent")
        self.assertIsNone(flow.credentials)

    async def test_continuity_uses_existing_scopes_without_logging_identifiers(self):
        other = object()
        with self.assertLogs(LOGGER, level="INFO") as logs:
            await self.phone.handle(self.frame("start"))
            await self.phone.handle(self.frame("start", chat="PRIVATE-other-chat"))
            await self.phone.handle(self.frame("start", connection=other))
            flow = self.phone.flows[self.phone.key(self.frame("", connection=other))]
            flow.expires = 0
            await self.phone.handle(self.frame("start", connection=other))
            await self.phone.handle(
                self.frame("start", connection=other, user="PRIVATE-other-user")
            )
        output = "\n".join(logs.output)
        for category in (
            "new_scope",
            "chat_changed",
            "connection_changed",
            "expired_scope",
            "account_changed",
        ):
            self.assertIn(f"continuity={category}", output)
        self.assertNotIn("PRIVATE", repr([entry.__dict__ for entry in logs.records]))
