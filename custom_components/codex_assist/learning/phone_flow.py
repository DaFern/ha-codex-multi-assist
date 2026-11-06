"""Phone turns scoped to an authenticated login/account/chat, never an LLM."""

import asyncio
import base64
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass, field

from .finalization import wait_for_final_state
from .learning_bridge_protocol import BridgeError
from .phone_diagnostics import record

MARKER = "Voice learning input"
NOTICE = (
    "Before we begin, I'll need to record some short samples of your voice so I can recognise you in future. "
    "Your recordings will be stored on this Home Assistant system, and you can stop at any time. "
    'If you\'re happy to continue, say "Start learning".'
)
INTRO = (
    "Great! I'll give you a few sentences to read aloud. "
    'You can say "Pause learning" to take a break, or "Cancel voice learning" to discard this session. '
    "Let's begin!"
)
PRIVACY_DETAILS = (
    "Voice learning makes recordings and a biometric voiceprint for your signed-in Home Assistant account. "
    "Recordings are stored by this system and deleted after a validated replacement is installed. "
    "Your selected speech-to-text service also processes your speech; its privacy and retention rules apply. "
    "Only you should use this phone microphone. Your existing voiceprint stays until its replacement validates. "
    "A voice match is not authentication. Pause learning keeps unfinished recordings. "
    "Cancel voice learning deletes only the bound unfinished session's recordings, not the installed voiceprint "
    "or old backups. Deleting files does not guarantee secure erasure from disk."
)
STOP = {
    "no",
    "stop",
    "pause",
    "stop learning",
    "pause learning",
    "stop voice learning",
    "pause voice learning",
}
CANCEL = {"cancel", "cancel learning", "cancel voice learning"}
STATUS = {"status", "check status", "continue"}


def control_category(text):
    """One control parser for dispatch and fixed-category diagnostics.

    Normalise control punctuation/spacing, not positive biometric consent.
    Ambiguous control-like speech is excluded from training, never used to delete.
    """
    command = text.casefold().strip(" .!?\r\n\t")
    if command == "start learning":
        return "start_learning"
    if command == "continue learning":
        return "continue_learning"
    if (
        (
            "record some short samples of your voice" in command
            and "home assistant system" in command
        )
        or (
            "welcome back" in command
            and "voice samples" in command
            and "continue learning" in command
        )
        or (
            "give you a few sentences to read aloud" in command
            and "cancel voice learning" in command
        )
        or ("biometric voiceprint" in command and "not authentication" in command)
    ):
        return "notice_like"
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())
    control = " ".join(words).removeprefix("please ").removesuffix(" please")
    if control in CANCEL:
        return "cancel"
    if control in STOP:
        return "stop"
    if control in STATUS:
        return "status"
    if control in {"privacy", "privacy details", "recording privacy"}:
        return "privacy"
    if control == "start learning":
        return "start_learning_punctuation"
    if control == "continue learning":
        return "continue_learning_punctuation"
    if (
        set(words) & {"pause", "stop", "cancel"}
        or (
            len(words) <= 6
            and (
                "learning" in words
                or set(words) & {"paws", "council", "counsel", "cancelled", "canceled", "pausing"}
            )
        )
        or control in {"learn my voice", "start voice learning"}
    ):
        return "uncertain_control"
    return "other"


@dataclass(repr=False)
class PhoneFrame:
    connection: object
    user_id: str
    conversation_id: str
    started_at: float
    audio: bytes
    text: str
    login_id: str | None = None
    permit: dict | None = None
    valid: bool = True


@dataclass
class PhoneReply:
    speech: str
    continue_conversation: bool = False


@dataclass(repr=False)
class PhoneFlow:
    connection: object
    user_id: str
    conversation_id: str
    profile_id: str
    login_id: str
    source: str = field(default_factory=lambda: "phone-" + secrets.token_hex(16))
    expires: float = field(default_factory=lambda: time.monotonic() + 120)
    issued: float = field(default_factory=time.monotonic)
    phase: str = "consent"
    credentials: dict | None = None
    permit: dict | None = None
    prompt: str = ""
    prompt_count: int | None = None
    must_reconsent: bool = False
    begin_uncertain: bool = False
    discard_uncertain: bool = False
    resume_snapshot: dict | None = None
    intro_pending: bool = True


class PhoneController:
    def __init__(self, bridge, *, authorize=None):
        self.bridge = bridge
        self.authorize = authorize
        self.flows = {}
        self.lock = asyncio.Lock()
        self.closing = False

    def key(self, frame):
        return (frame.login_id, frame.user_id, frame.conversation_id)

    def check(self, frame):
        if (
            not frame.valid
            or not frame.login_id
            or (
                self.authorize is not None
                and self.authorize(frame.connection, frame.user_id) != frame.login_id
            )
        ):
            raise ValueError("Authenticated phone turn unavailable")

    async def prepare(self, connection, user_id, conversation_id, login_id):
        """Issue a fresh permit before this authenticated turn captures any PCM."""
        async with self.lock:
            if self.authorize is not None and self.authorize(connection, user_id) != login_id:
                raise ValueError("Authenticated phone login unavailable")
            flow = self.flows.get((login_id, user_id, conversation_id))
            if self.closing or flow is None:
                return None
            flow.connection = connection
            if (
                flow.must_reconsent
                or flow.discard_uncertain
                or flow.expires <= time.monotonic()
                or flow.phase != "sample"
                or flow.credentials is None
            ):
                return None
            try:
                state = await self.bridge.call("state", user_id, flow.credentials)
                if (
                    state["outcome"] != "active"
                    or state["processing"]
                    or state["error"]
                    or state["count"] != flow.prompt_count
                ):
                    flow.phase = "attention"
                    return None
                if self.authorize is not None and self.authorize(connection, user_id) != login_id:
                    raise ValueError("Authenticated phone login unavailable")
                permit = await self.bridge.call("permit", user_id, flow.credentials)
                if permit["count"] != flow.prompt_count:
                    flow.phase = "attention"
                    return None
                return permit
            except BaseException:
                flow.phase = "attention"
                raise

    def connection_lost(self, connection, *, completed):
        """Synchronous invalidation before asynchronous disconnect cleanup."""
        for flow in self.flows.values():
            if flow.connection is connection:
                flow.permit = None
                if completed:
                    flow.connection = None
                else:
                    flow.must_reconsent = True

    async def _pause(self, key, flow, *, retain=False):
        if flow.discard_uncertain:
            # Disconnect/chat changes cannot silently convert unknown deletion
            # into a successful pause or allow a fresh begin over that session.
            return False
        if flow.credentials is None and not flow.begin_uncertain:
            self.flows.pop(key, None)
            return True
        if flow.expires <= time.monotonic():
            # Dead credentials cannot accept new audio. Do not claim a pending
            # generation was cancelled, but local phone state may be forgotten.
            self.flows.pop(key, None)
            return False
        if flow.credentials is not None:
            try:
                result = await self.bridge.call("cancel", flow.user_id, flow.credentials)
                if result.get("outcome") in {"paused", "complete", "expired", "cancelled"}:
                    if retain and not flow.must_reconsent and result.get("outcome") == "paused":
                        flow.phase, flow.permit, flow.resume_snapshot = "paused", None, None
                    else:
                        self.flows.pop(key, None)
                    return True
            except BridgeError:
                pass
        flow.phase = "attention"
        flow.permit = None
        return False

    async def _resume_notice(self, flow, frame):
        """Read current, authorised paused-generation metadata without beginning recording."""
        self.check(frame)
        frame.audio, frame.permit = b"", None
        flow.resume_snapshot = None
        try:
            snapshot = await self.bridge.call("resume_preview", frame.user_id, flow.credentials)
        except BridgeError:
            return PhoneReply(
                "I couldn't verify your paused session. No learning has resumed. Check Voice Match management."
            )
        self.check(frame)
        if (
            snapshot.get("id") != flow.profile_id
            or type(snapshot.get("count")) is not int
            or type(snapshot.get("target")) is not int
            or not 0 <= snapshot["count"] < snapshot["target"] <= 100
        ):
            return PhoneReply(
                "I couldn't verify your saved progress. No learning has resumed. Check Voice Match management."
            )
        flow.resume_snapshot = snapshot
        flow.phase, flow.issued = "resume_consent", time.monotonic()
        flow.expires = min(flow.expires, flow.issued + 120)
        record("flow", "resume_notice")
        return PhoneReply(
            f"Welcome back! You've completed {snapshot['count']} of {snapshot['target']} voice samples. "
            'Say "Continue learning" when you\'re ready to carry on. '
            'Say "Cancel voice learning" to discard your unfinished recordings.',
            True,
        )

    async def _discard(self, key, flow, frame):
        """Delete only via the backend's bound-session operation; never broad cleanup."""
        flow.phase, flow.permit = "attention", None
        if flow.credentials is None or flow.expires <= time.monotonic():
            return PhoneReply(
                "Cancellation could not be verified. Check Voice Match management. Recordings may still be kept."
            )
        self.check(frame)
        flow.discard_uncertain = True  # A lost response must not trigger a retry.
        try:
            result = await self.bridge.call(
                "discard",
                frame.user_id,
                {
                    **flow.credentials,
                    "confirm": True,
                },
            )
            if result.get("outcome") == "cancelled":
                self.flows.pop(key, None)
                record("flow", "cancel_discarded")
                return PhoneReply(
                    "Voice learning cancelled. This unfinished session's recordings were deleted. Your existing voiceprint is unchanged."
                    " If you're finished with voice learning, remember to switch back to your regular assistant."
                )
        except BridgeError:
            pass
        record("flow", "cancel_unverified")
        return PhoneReply(
            "Cancellation could not be verified. No further samples will be recorded. Check Voice Match management; recordings may still be kept."
        )

    async def _next(self, flow, frame):
        self.check(frame)
        state = await self.bridge.call("state", flow.user_id, flow.credentials)
        state = await wait_for_final_state(self, flow, frame, state)
        self.check(frame)
        if state["error"]:
            flow.phase, flow.permit = "attention", None
            return PhoneReply(
                "Voice processing needs attention. Say pause, or check Voice Match management."
            )
        if state["outcome"] == "complete":
            self.flows.pop((flow.login_id, flow.user_id, flow.conversation_id), None)
            return PhoneReply(
                "Your replacement voiceprint validated and the saved samples were cleaned up. Voice learning is complete."
                " If you're finished with voice learning, remember to switch back to your regular assistant."
            )
        if state["outcome"] != "active":
            flow.phase, flow.permit = "attention", None
            return PhoneReply(
                "This learning session has ended. Start a new conversation for fresh consent."
            )
        if state["processing"]:
            flow.phase, flow.permit = "processing", None
            return PhoneReply(
                "Your voice recording is still processing. This check has ended. "
                "Check Voice Match management, or ask for status. Do not read another sample yet."
            )
        self.check(frame)
        permit = await self.bridge.call("permit", flow.user_id, flow.credentials)
        # This permit supplies the prompt only. It is never retained for upload;
        # prepare() rotates it for each exact authenticated recording turn.
        flow.permit, flow.phase = None, "sample"
        flow.prompt_count = permit["count"]
        flow.issued = time.monotonic()
        prefix = "Sample not saved. Please try again. " if state["notice"] else ""
        flow.prompt = f"{prefix}Sample {permit['count'] + 1} of {state['target']}. Read aloud: {permit['prompt']}"
        introduction = INTRO + " " if flow.intro_pending and state["count"] == 0 else ""
        flow.intro_pending = False
        return PhoneReply(introduction + flow.prompt, True)

    async def handle(self, frame):
        if self.closing or not frame.valid or not frame.login_id:
            record("flow", "closing")
            return PhoneReply("Phone voice learning is unavailable.")
        async with asyncio.timeout(60), self.lock:
            self.check(frame)
            previous = self.flows.get(self.key(frame))
            needs_fresh_consent = bool(
                previous and (previous.must_reconsent or previous.expires <= time.monotonic())
            )
            if previous is not None:
                continuity = (
                    "expired_scope" if previous.expires <= time.monotonic() else "same_scope"
                )
            elif any(
                flow.login_id == frame.login_id and flow.user_id == frame.user_id
                for flow in self.flows.values()
            ):
                continuity = "chat_changed"
            elif any(flow.user_id == frame.user_id for flow in self.flows.values()):
                continuity = "connection_changed"
                needs_fresh_consent = True
            elif any(flow.connection is frame.connection for flow in self.flows.values()):
                continuity = "account_changed"
            else:
                continuity = "new_scope"
            record(
                "flow",
                "received",
                control=control_category(frame.text),
                continuity=continuity,
                phase=previous.phase if previous is not None else "none",
                audio_bytes=len(frame.audio),
            )
            # A different chat or authenticated login cannot inherit consent.
            for key, previous in list(self.flows.items()):
                if previous.expires <= time.monotonic() and not previous.discard_uncertain:
                    self.flows.pop(key, None)
                elif (
                    previous.login_id == frame.login_id
                    and previous.user_id == frame.user_id
                    and previous.conversation_id != frame.conversation_id
                ):
                    needs_fresh_consent = True
                    if not await self._pause(key, previous):
                        return PhoneReply(
                            "The previous learning session needs attention or is still processing. Check Voice Match management before starting again."
                        )
            key = self.key(frame)
            flow = self.flows.get(key)
            command = frame.text.casefold().strip(" .!?\r\n\t")
            control = control_category(frame.text)
            if flow is not None and flow.discard_uncertain:
                frame.audio, frame.permit = b"", None
                # Read-only receipt recovery, not a repeat destructive request.
                self.check(frame)
                try:
                    state = await self.bridge.call("state", frame.user_id, flow.credentials)
                    if state.get("outcome") == "cancelled":
                        self.flows.pop(key, None)
                        return PhoneReply(
                            "Voice learning cancelled. This unfinished session's recordings were deleted. Your existing voiceprint is unchanged."
                            " If you're finished with voice learning, remember to switch back to your regular assistant."
                        )
                except BridgeError:
                    pass
                return PhoneReply(
                    "Cancellation is still unverified. Check Voice Match management before starting again."
                )
            if control in {"stop", "cancel"}:
                frame.audio, frame.permit = b"", None
                if flow is None:
                    record("flow", "stop_no_session")
                    return PhoneReply(
                        "There is no active voice learning session in this conversation. Any earlier paused recordings are unchanged."
                    )
                if flow.credentials is None and not flow.begin_uncertain:
                    self.flows.pop(key, None)
                    record("flow", "cancel_before_start")
                    return PhoneReply(
                        "Voice learning cancelled. No learning started in this conversation. Any earlier paused recordings are unchanged."
                        " If you're finished with voice learning, remember to switch back to your regular assistant."
                    )
                if control == "cancel":
                    if frame.started_at <= flow.issued:
                        return PhoneReply(
                            "That cancellation recording began before the current prompt. Nothing was deleted. Close Assist and check Voice Match management."
                        )
                    return await self._discard(key, flow, frame)
                if await self._pause(key, flow, retain=True):
                    record("flow", "stop_paused")
                    return PhoneReply(
                        "Voice learning is paused. Partial samples are kept for an explicitly consented resume."
                        " If you're finished with voice learning, remember to switch back to your regular assistant."
                    )
                record("flow", "stop_unverified")
                return PhoneReply(
                    "I could not verify the pause. Processing may still be running; check Voice Match management."
                )
            if flow is not None and flow.must_reconsent:
                if not await self._pause(key, flow):
                    return PhoneReply(
                        "The interrupted learning session needs attention. Check Voice Match management before starting again."
                    )
                flow = None
                needs_fresh_consent = True
            if flow is not None and flow.phase in {"paused", "resume_consent"}:
                flow.connection = frame.connection
                if flow.phase == "resume_consent" and frame.started_at <= flow.issued:
                    return PhoneReply(
                        "That recording began before the resume prompt. Please wait for the prompt to finish and record again."
                    )
                if (
                    flow.phase == "resume_consent"
                    and command == "continue learning"
                    and flow.resume_snapshot is not None
                ):
                    snapshot, credentials = flow.resume_snapshot, flow.credentials
                    self.check(frame)
                    flow.resume_snapshot, flow.credentials = None, None
                    flow.phase, flow.begin_uncertain = "attention", True
                    frame.audio, frame.permit = b"", None
                    result = await self.bridge.call(
                        "resume",
                        frame.user_id,
                        {
                            **credentials,
                            "count": snapshot["count"],
                            "target": snapshot["target"],
                            "consent": True,
                        },
                    )
                    flow.credentials = {
                        "session_token": result["session_token"],
                        "source": flow.source,
                    }
                    flow.begin_uncertain, flow.intro_pending = False, False
                    flow.expires = time.monotonic() + 900
                    record("flow", "resume_started")
                    return await self._next(flow, frame)
                reply = await self._resume_notice(flow, frame)
                if control == "privacy":
                    reply.speech = PRIVACY_DETAILS + " " + reply.speech
                return reply
            if control == "privacy" and flow is not None:
                frame.audio, frame.permit = b"", None
                if flow.credentials is not None:
                    reply = await self._next(flow, frame)
                    reply.speech = PRIVACY_DETAILS + " " + reply.speech
                    return reply
                if not flow.begin_uncertain:
                    flow.issued = time.monotonic()
                    return PhoneReply(PRIVACY_DETAILS + " " + NOTICE, True)
            if (
                flow is not None
                and flow.credentials is not None
                and control
                in {
                    "uncertain_control",
                    "notice_like",
                    "start_learning",
                    "start_learning_punctuation",
                    "continue_learning",
                    "continue_learning_punctuation",
                }
            ):
                frame.audio, frame.permit = b"", None
                if await self._pause(key, flow, retain=True):
                    record("flow", "control_guard_paused")
                    return PhoneReply(
                        "That sounded like a learning control, so it was not saved. Learning is paused and unfinished recordings are kept. Ask to continue when you're ready."
                        " If you're finished with voice learning, remember to switch back to your regular assistant."
                    )
                return PhoneReply(
                    "That recording was not submitted. I could not verify the pause. Close Assist and check Voice Match management."
                )
            if flow is None:
                if len(self.flows) >= 16:
                    return PhoneReply("Phone learning is busy. Try again later.")
                own = await self.bridge.call("own_profile", frame.user_id, {})
                if not own.get("id"):
                    return PhoneReply(
                        "You need an existing voice profile explicitly assigned to your account. Ask an administrator to check Voice Match management."
                    )
                flow = PhoneFlow(
                    frame.connection,
                    frame.user_id,
                    frame.conversation_id,
                    own["id"],
                    frame.login_id,
                )
                self.flows[key] = flow
                record("flow", "notice_new")
                prefix = (
                    "For privacy, please confirm again before continuing. "
                    if needs_fresh_consent
                    else ""
                )
                if control == "privacy":
                    prefix += PRIVACY_DETAILS + " "
                return PhoneReply(prefix + NOTICE, True)  # The first request is never consent.
            flow.connection = frame.connection
            if frame.started_at <= flow.issued:
                record("flow", "stale_turn")
                return PhoneReply(
                    "That recording began before the current prompt. Please wait for the prompt to finish and record again."
                )
            if flow.phase == "consent":
                if command != "start learning":
                    record("flow", "notice_repeat")
                    flow.issued = time.monotonic()
                    return PhoneReply(NOTICE, True)
                flow.phase, flow.expires = "attention", time.monotonic() + 900
                self.check(frame)
                flow.begin_uncertain = True
                result = await self.bridge.call(
                    "begin",
                    frame.user_id,
                    {
                        "id": flow.profile_id,
                        "source": flow.source,
                        "own_only": True,
                        "consent": True,
                        "isolation_confirmed": True,
                    },
                )
                flow.credentials = {"session_token": result["session_token"], "source": flow.source}
                flow.begin_uncertain = False
                return await self._next(flow, frame)  # Consent audio is discarded, never submitted.
            if flow.phase in {"processing", "attention"} or control == "status":
                if flow.credentials is not None:
                    return await self._next(flow, frame)  # Status/recovery turns are not samples.
                return PhoneReply(
                    "Setup could not be verified. Check Voice Match management; do not repeat setup blindly."
                )
            permit, frame.permit = frame.permit, None
            if permit is None or permit["count"] != flow.prompt_count or not frame.valid:
                return PhoneReply(
                    "There is no recording permit. Ask for status before recording again."
                )
            flow.phase = "attention"  # Lost/cancelled responses cannot reuse this clip.
            self.check(frame)
            await self.bridge.call(
                "sample",
                frame.user_id,
                {
                    **flow.credentials,
                    "permit": permit["permit"],
                    "audio": base64.b64encode(frame.audio).decode(),
                },
            )
            return await self._next(flow, frame)

    async def disconnect(self, connection):
        async with self.lock:
            results = [
                await self._pause(key, flow)
                for key, flow in list(self.flows.items())
                if flow.connection is connection
            ]
            return all(results)

    async def shutdown(self):
        self.closing = True
        async with self.lock:
            results = await asyncio.gather(
                *(self._pause(key, flow) for key, flow in list(self.flows.items()))
            )
            return all(results)
