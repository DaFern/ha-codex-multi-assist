"""Non-LLM learning agent; raw audio only arrives through its exact native turn."""

from homeassistant.components import conversation
from homeassistant.components.websocket_api.connection import current_connection
from homeassistant.helpers import chat_session, intent

from .phone_diagnostics import record
from .phone_flow import MARKER, PhoneReply


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = entry.runtime_data.phone
    if runtime is not None:
        async_add_entities([PhoneLearningAgent(entry, runtime)])


class PhoneLearningAgent(conversation.ConversationEntity):
    _attr_has_entity_name = True
    _attr_name = "Voice Learning"

    def __init__(self, entry, runtime):
        self._attr_unique_id = entry.entry_id + "_phone_learning_agent"
        self.runtime = runtime

    @property
    def supported_languages(self):
        return ["en"]

    async def _async_handle_message(self, user_input, chat_log):
        frame = None
        reply = PhoneReply(
            "Use the microphone in the dedicated Voice Learning assistant. "
            "No recording was submitted."
        )
        try:
            connection = current_connection.get()
            if user_input.text != MARKER or not user_input.context.user_id or connection is None:
                record("agent", "binding")
                return self._reply(user_input, reply)
            frame = self.runtime.frames.take(
                connection,
                user_input.context.user_id,
                chat_session.current_session.get(),
                user_input.conversation_id,
            )
            user = await self.hass.auth.async_get_user(user_input.context.user_id)
            if (
                frame is None
                or user is None
                or not user.is_active
                or user.system_generated
                or connection.user.id != user.id
                or self.runtime.authorize(connection, user.id) != frame.login_id
            ):
                record("agent", "account_or_metadata" if frame is not None else "missing")
                return self._reply(user_input, reply)
            reply = await self.runtime.controller.handle(frame)
            self.runtime.complete(frame)
        except Exception:  # noqa: BLE001 - Keep peer/account/biometric details out of native error traces.
            record("agent", "failed")
            if frame is not None:
                flow = self.runtime.controller.flows.get(self.runtime.controller.key(frame))
                if flow is not None:
                    flow.phase, flow.permit = "attention", None
                    flow.must_reconsent = True
            reply = PhoneReply(
                "Learning could not be verified. Say pause or status, or check Voice Match "
                "management. Do not repeat setup blindly."
            )
        finally:
            if frame is not None:
                frame.audio, frame.text = b"", ""
                frame.permit, frame.valid = None, False
        return self._reply(user_input, reply)

    def _reply(self, user_input, reply):
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(reply.speech)
        return conversation.ConversationResult(
            response=response,
            conversation_id=user_input.conversation_id,
            continue_conversation=reply.continue_conversation,
        )
