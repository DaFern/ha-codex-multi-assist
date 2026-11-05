"""Device-independent learning lifecycle, with no stock pipeline interception.

Only an in-process trusted adapter can provide a reserved lease. A device label
from a WebSocket caller is never sufficient. No real adapter ships in this stage.
"""

import asyncio
import base64


class Coordinator:
    def __init__(self, bridge, task_factory=asyncio.create_task, poll_seconds=0.2):
        self.bridge = bridge
        self._task_factory = task_factory
        self._poll_seconds = poll_seconds
        self._task = None
        self._cancel_requested = False
        self._cleaning = False
        self._lease = None
        self._release_lock = asyncio.Lock()
        self.actor_id = None
        self._state = {"outcome": "idle", "count": 0, "target": 0, "restored": None}

    def view(self):
        return dict(self._state)

    @property
    def running(self):
        return self._task is not None and not self._task.done()

    async def start(self, actor_id, voice_id, speaker, *, consent):
        if (
            consent is not True
            or speaker is None
            or not callable(getattr(speaker, "reserve", None))
        ):
            raise ValueError("Fresh consent and a trusted device adapter are required")
        if self.running:
            raise ValueError("Learning is already running")
        if self._lease is not None:
            raise ValueError("The previous device reservation still needs restoration")
        self.actor_id = actor_id
        self._cancel_requested = False
        self._cleaning = False
        self._state = {"outcome": "starting", "count": 0, "target": 0, "restored": None}
        self._task = self._task_factory(self._run(actor_id, voice_id, speaker))

    async def wait(self):
        if self._task is not None:
            await self._task

    async def cancel(self):
        if self.running:
            if not self._cancel_requested and not self._cleaning:
                self._cancel_requested = True
                self._task.cancel()
            try:
                await asyncio.shield(self._task)
            except asyncio.CancelledError:
                self._state["outcome"] = "paused"
        elif self._lease is not None:
            # An explicit later cancel/unload can retry idempotent restoration;
            # never discard a failed lease or start a new session over it.
            await self._restore()

    async def _restore(self):
        async with self._release_lock:
            if self._lease is None:
                return
            try:
                await asyncio.wait_for(self._lease.release(), 20)
                self._lease = None
                self._state["restored"] = True
            except Exception:  # noqa: BLE001 - Retain an unknown restoration failure for explicit recovery.
                self._state.update(outcome="attention", restored=False)

    async def _run(self, actor_id, voice_id, speaker):
        lease = credentials = None
        completed = False
        try:
            async with asyncio.timeout(900):
                result = await self.bridge.call(
                    "begin",
                    actor_id,
                    {
                        "id": voice_id,
                        "source": speaker.source_id,
                        "consent": True,
                        "isolation_confirmed": True,
                    },
                )
                credentials = {
                    "source": speaker.source_id,
                    "session_token": result["session_token"],
                }
                # Ownership approval precedes reserving/opening a device. The
                # adapter must restore its own partial work if reserve fails.
                lease = await asyncio.wait_for(speaker.reserve(), 10)
                self._lease = lease
                attempts = 0
                while True:
                    state = await self.bridge.call("state", actor_id, credentials)
                    self._state.update(count=state["count"], target=state["target"])
                    if state["error"]:
                        self._state["outcome"] = "attention"
                        break
                    if state["outcome"] == "complete":
                        completed = True
                        self._state["outcome"] = "complete"
                        break
                    if state["outcome"] != "active":
                        self._state["outcome"] = "paused"
                        break
                    if state["processing"]:
                        self._state["outcome"] = "processing"
                        await asyncio.sleep(self._poll_seconds)
                        continue
                    if attempts >= 3:
                        self._state["outcome"] = "paused"
                        break
                    permit = await self.bridge.call("permit", actor_id, credentials)
                    self._state["outcome"] = "prompting"
                    # speak() must return only after playback ends. Recording
                    # never overlaps guidance/TTS or goes to a conversation agent.
                    prompt = (
                        f"Sample {permit['count'] + 1} of {state['target']}. "
                        f"Please repeat: {permit['prompt']}"
                    )
                    await asyncio.wait_for(lease.speak(prompt), 15)
                    self._state["outcome"] = "recording"
                    audio = await asyncio.wait_for(lease.record(), 12)
                    if audio is None:  # Explicit cancel/stop from the reserved source.
                        self._state["outcome"] = "paused"
                        break
                    if not isinstance(audio, bytes) or len(audio) > 320000 or len(audio) % 2:
                        raise ValueError("Unsupported recording")
                    await self.bridge.call(
                        "sample",
                        actor_id,
                        {
                            **credentials,
                            "permit": permit["permit"],
                            "audio": base64.b64encode(audio).decode(),
                        },
                    )
                    del audio
                    self._state["outcome"] = "processing"
                    # Observe saved count, never assume that HTTP 202 means saved.
                    while True:
                        state = await self.bridge.call("state", actor_id, credentials)
                        if not state["processing"]:
                            break
                        await asyncio.sleep(self._poll_seconds)
                    attempts = attempts + 1 if state["count"] == permit["count"] else 0
        except asyncio.CancelledError:
            self._state["outcome"] = "paused"
        except Exception:  # noqa: BLE001 - Device/transport faults must still release the source, without leaking peer errors.
            self._state["outcome"] = "attention"
        finally:
            self._cleaning = True
            # Independent, bounded cleanup: a failed backend cannot prevent the
            # selected device being released, and failures are never called success.
            if credentials is not None and not completed:
                try:
                    await asyncio.wait_for(self.bridge.call("cancel", actor_id, credentials), 20)
                except Exception:  # noqa: BLE001 - Backend failure cannot prevent independent device cleanup.
                    self._state["outcome"] = "attention"
            if lease is not None:
                await self._restore()
