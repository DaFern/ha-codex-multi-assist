"""Bounded read-only completion wait within the existing authenticated phone turn."""

import asyncio
import time

FINAL_WAIT_SECONDS = 15
POLL_INTERVAL = 0.5
MAX_STATE_CHECKS = 30


async def wait_for_final_state(controller, flow, frame, state):
    """Wait only for the last prompted sample; never retry an audio mutation."""
    target = state.get("target")
    if (
        state.get("outcome") != "active"
        or not state.get("processing")
        or state.get("error")
        or type(target) is not int
        or not 1 <= target <= 100
        or flow.prompt_count != target - 1
    ):
        return state

    def check_scope():
        controller.check(frame)
        if (
            controller.closing
            or flow.must_reconsent
            or flow.expires <= time.monotonic()
            or controller.flows.get(controller.key(frame)) is not flow
        ):
            raise ValueError("Authenticated completion wait unavailable")

    def check_state(value):
        if (
            value.get("id") != flow.profile_id
            or type(value.get("target")) is not int
            or value.get("target") != target
            or type(value.get("count")) is not int
            or not 0 <= value["count"] <= target
            or (
                value.get("outcome") == "complete"
                and (value.get("error") is not False or value["count"] != target)
            )
        ):
            raise ValueError("Completion progress could not be verified")

    check_scope()
    check_state(state)
    try:
        async with asyncio.timeout(FINAL_WAIT_SECONDS):
            for _ in range(MAX_STATE_CHECKS):
                await asyncio.sleep(POLL_INTERVAL)
                check_scope()
                updated = await controller.bridge.call("state", flow.user_id, flow.credentials)
                check_scope()
                check_state(updated)
                state = updated
                # The backend sets complete only after validation and cleanup;
                # processing can remain true briefly during provider reload.
                if (
                    state.get("error")
                    or state.get("outcome") != "active"
                    or not state.get("processing")
                ):
                    return state
    except TimeoutError:
        # Only a read was interrupted. Preserve the last verified state; never
        # infer completion, resend audio, or retry a failed bridge operation.
        pass
    check_scope()
    return state
