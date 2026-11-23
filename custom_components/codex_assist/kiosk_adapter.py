"""Experimental opt-in ESPHome instance hooks with approved constructor interception.

Private HA/aioesphomeapi details are version-sensitive. An unsupported shape,
plaintext connection, changed registry/client/configuration or lost connection
denies the turn. This module never replaces an ESPHome entity or subscription.
"""

import asyncio
import time
from importlib import import_module

from homeassistant.components import conversation
from homeassistant.components.assist_pipeline import (
    PipelineEvent,
    PipelineEventType,
    PipelineStage,
    async_get_pipeline,
)
from homeassistant.components.assist_satellite.const import DATA_COMPONENT
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er

from .guest_policy import ORDINARY_DOMAINS
from .protected_conversation import (
    LISTEN_SECONDS,
    ProtectedConversation,
    SpeechActivity,
    is_forget_phrase,
    is_stop_phrase,
)
from .protected_model import async_entry_voice_handler
from .protected_pipeline import async_run_protected_pipeline
from .rbac_satellite import ProtectedSatelliteDispatcher

CONF_PROTECTED_SATELLITES = "protected_satellite_ids"
DATA_ADAPTERS = "codex_assist_protected_satellites"
DATA_GUARDS = "codex_assist_protected_guards"
DATA_HISTORY = "codex_assist_protected_history"
HOOK = "async_accept_pipeline_from_satellite"


def _native_types():
    """Lazy imports keep ordinary/minimum-version entry setup independent."""
    from aioesphomeapi import APIClient
    from aioesphomeapi.connection import APIConnection
    from homeassistant.components.esphome.assist_satellite import EsphomeAssistSatellite
    from homeassistant.components.esphome.entry_data import RuntimeEntryData

    return EsphomeAssistSatellite, RuntimeEntryData, APIClient, APIConnection


class KioskSatelliteAdapter:
    """Entry-owned hooks and leases, never an externally callable service/API."""

    def __init__(self, hass, entry, approved_satellite_ids):
        from .conversation import CodexAssistConversationEntity
        from .protected_history import SharedSatelliteHistory

        self.hass, self.entry = hass, entry
        self._agent_type = CodexAssistConversationEntity
        self._approved = frozenset(approved_satellite_ids)
        self._options = entry.options
        self._closed = False
        self._hooks = {}
        self._tasks = {}
        self._followups = {}
        self._bindings = {}
        self._connection_checks = {}
        self._removers = {}
        self._conversations = {}
        self._completion_hooks = {}
        self._enrollments = {}
        self._constructor = None
        self._guards = hass.data.setdefault(DATA_GUARDS, {})
        histories = hass.data.setdefault(DATA_HISTORY, {})
        if entry.entry_id not in histories:
            histories[entry.entry_id] = SharedSatelliteHistory(hass, entry.entry_id, self._approved)
        self._history = histories[entry.entry_id]
        self._history.set_approved(self._approved)
        provider = import_module("custom_components.ha_rbac.satellite_admission")
        if type(provider.SATELLITE_ADMISSION_VERSION) is not int:
            raise ValueError("Unsupported admission provider")
        if provider.SATELLITE_ADMISSION_VERSION != 1:
            raise ValueError("Unsupported admission provider")
        dispatcher = ProtectedSatelliteDispatcher.for_entry(
            hass, entry, candidate_entity_ids=self._candidates,
        )
        self.ingress = provider.SatelliteAdmissionRegistry(
            hass, dispatcher, approved_satellite_ids=self._approved,
        )

    def _candidates(self):
        return tuple(sorted(
            state.entity_id for state in self.hass.states.async_all()
            if state.domain in ORDINARY_DOMAINS
        ))

    def _entity(self, eid):
        component = self.hass.data.get(DATA_COMPONENT)
        return component.get_entity(eid) if component is not None else None

    def install(self):
        """Install scoped hooks. Failed setup keeps installed enrollment fail-closed."""
        native, *_ = _native_types()
        from .kiosk_lifecycle import enroll_constructor

        if not self._approved or len(self._approved) > 32:
            raise ValueError("Invalid protected satellite enrollment")
        try:
            for eid in sorted(self._approved):
                satellite = self._entity(eid)
                registered = er.async_get(self.hass).async_get(eid)
                if (
                    registered is None
                    or registered.platform != "esphome" or registered.disabled_by is not None
                    or registered.device_id is None
                    or (satellite is not None and type(satellite) is not native)
                ):
                    raise ValueError("Satellite unavailable or already hooked")
                self._enrollments[eid] = self._registry_identity(registered)
                self._constructor = enroll_constructor(
                    native, self, eid, registered.config_entry_id,
                )
                # Missing entities are guarded when constructed, not retried later
                # by a state-change listener after an unprotected activation window.
                if satellite is not None:
                    self.attach_instance(eid, satellite)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _registry_identity(registered):
        return (
            registered.id, registered.unique_id, registered.platform,
            registered.config_entry_id, registered.device_id,
        )

    def attach_instance(self, eid, satellite, *, constructed=False):
        """Install before construction returns; old instances never regain authority."""
        previous_guard = self._guards.get(eid)
        own = self._hooks.get(eid)
        if own is not None and own[0] is satellite:
            if satellite.__dict__.get(HOOK) is own[1]:
                return
            raise ValueError("Protected instance hook was replaced")
        takeover = (
            previous_guard is not None and previous_guard[0]._closed
            and previous_guard[0].entry is self.entry
            and previous_guard[1] is satellite
            and satellite.__dict__.get(HOOK) is previous_guard[2]
        )
        if HOOK in satellite.__dict__ and not takeover:
            raise ValueError("Satellite already has a foreign instance hook")
        previous = previous_guard[3] if takeover else satellite.__dict__.get(HOOK)
        self._drop_conversation(eid)
        self._restore_completion_hook(eid)

        # Revoke before publishing the new hook. Closing the old binding also
        # cancels active admission work; STT/TTS-only tasks are cancelled here too.
        old = self._bindings.pop(eid, None)
        if old is not None:
            old[1].close()
        remove = self._removers.pop(eid, None)
        if remove is not None:
            remove()
        for task, entity in tuple(self._tasks.items()):
            if entity is not satellite and entity.entity_id == eid:
                task.cancel()

        async def accept(
            audio_stream, start_stage=PipelineStage.STT, end_stage=PipelineStage.TTS,
            wake_word_phrase=None, *, context=None,
        ):
            # A constructed instance might receive a different registry identity
            # or entity ID during add. It remains guarded but cannot act.
            registered = er.async_get(self.hass).async_get(eid)
            if (
                satellite.entity_id != eid or registered is None
                or self._registry_identity(registered) != self._enrollments[eid]
                or (constructed and satellite.unique_id != registered.unique_id)
                or self._hooks.get(eid, (None,))[0] is not satellite
            ):
                satellite._internal_on_pipeline_event(PipelineEvent(PipelineEventType.ERROR, {
                    "code": "protected-satellite-denied",
                    "message": "Protected satellite identity changed.",
                }))
                satellite._internal_on_pipeline_event(PipelineEvent(PipelineEventType.RUN_END))
                return
            await self._accept(
                satellite, audio_stream, start_stage, end_stage, wake_word_phrase, context,
            )

        self._hooks[eid] = satellite, accept, previous
        setattr(satellite, HOOK, accept)
        self._guards[eid] = self, satellite, accept, previous
        finished = getattr(satellite, "tts_response_finished", None)
        if callable(finished):
            previous_finished = satellite.__dict__.get("tts_response_finished")
            if takeover:
                old = previous_guard[0]._completion_hooks.get(eid)
                if old is not None and previous_finished is old[1]:
                    previous_finished, finished = old[2], old[3]

            def playback_finished():
                finished()
                self._arm_window(satellite)

            self._completion_hooks[eid] = (
                satellite, playback_finished, previous_finished, finished,
            )
            satellite.tts_response_finished = playback_finished

    def _restore_completion_hook(self, eid):
        old = self._completion_hooks.pop(eid, None)
        if old is not None:
            satellite, hook, previous, _original = old
            if satellite.__dict__.get("tts_response_finished") is hook:
                if previous is None:
                    delattr(satellite, "tts_response_finished")
                else:
                    satellite.tts_response_finished = previous

    def _drop_conversation(self, eid, connection=None):
        record = self._conversations.get(eid)
        if record is not None and (connection is None or record[0] is connection):
            self._conversations.pop(eid)
            record[1].clear()

    def _conversation(self, eid, connection):
        record = self._conversations.get(eid)
        if record is None or record[0] is not connection:
            self._drop_conversation(eid)
            record = self._conversations[eid] = connection, ProtectedConversation()
        return record[1]

    def _arm_window(self, satellite):
        """Native playback completion starts the microphone's short follow-up window."""
        eid = satellite.entity_id
        record = self._conversations.get(eid)
        if (
            self._closed or record is None
            or self._hooks.get(eid, (None,))[0] is not satellite
        ):
            return
        connection, state = record
        if state.open_window():
            state.timer = asyncio.get_running_loop().call_later(
                LISTEN_SECONDS, self._expire_window, satellite, connection, state,
            )

    def _expire_window(self, satellite, connection, state):
        eid = satellite.entity_id
        record = self._conversations.get(eid)
        if record is None or record[0] is not connection or record[1] is not state:
            return
        if state.speech_started:
            return
        self._drop_conversation(eid, connection)
        tasks = [task for task, entity in tuple(self._tasks.items()) if entity is satellite]
        for task in tasks:
            task.cancel()
        if not self._closed and self._hooks.get(eid, (None,))[0] is satellite:
            try:
                # Clear the device's continuation flag before ending silent capture,
                # so silence cannot recursively start another listening turn.
                satellite._internal_on_pipeline_event(PipelineEvent(PipelineEventType.INTENT_END, {
                    "intent_output": {
                        "response": {"speech": {"plain": {"speech": ""}}},
                        "conversation_id": "", "continue_conversation": False,
                    },
                }))
                if not tasks:
                    satellite._internal_on_pipeline_event(PipelineEvent(PipelineEventType.RUN_END))
            except Exception:
                pass  # A disconnected microphone cannot retain an active listening window.

    def _binding(self, satellite):
        """Bind the actual authenticated server-side connection, never its label."""
        native, runtime_type, client_type, connection_type = _native_types()
        registered = er.async_get(self.hass).async_get(satellite.entity_id)
        if registered is None:
            raise ValueError("Missing satellite")
        esphome_entry = self.hass.config_entries.async_get_entry(registered.config_entry_id)
        runtime = esphome_entry.runtime_data if esphome_entry is not None else None
        client = getattr(runtime, "client", None)
        connection = getattr(client, "_connection", None)
        data = esphome_entry.data if esphome_entry is not None else None
        options = esphome_entry.options if esphome_entry is not None else None

        def current(actual):
            try:
                return (
                    not self._closed and self.entry.options is self._options
                    and self._entity(satellite.entity_id) is satellite
                    and type(satellite) is native
                    and satellite.available is True
                    and satellite.config_entry is esphome_entry
                    and esphome_entry.domain == "esphome"
                    and esphome_entry.runtime_data is runtime
                    and esphome_entry.data is data and esphome_entry.options is options
                    and type(runtime) is runtime_type and runtime.available is True
                    and runtime.client is client and satellite.cli is client
                    and satellite._entry_data is runtime
                    and type(client) is client_type
                    # Plaintext does not prove the remote device's authenticity.
                    and isinstance(client.noise_psk, str) and bool(client.noise_psk)
                    and client.is_connected is True and actual is connection
                    and type(connection) is connection_type
                    and client._connection is connection and connection.is_connected is True
                    and self.hass.config_entries.async_get_entry(esphome_entry.entry_id)
                    is esphome_entry
                    and getattr(satellite, HOOK) is self._hooks[satellite.entity_id][1]
                )
            except Exception:
                return False

        if not current(connection):
            raise ValueError("Authenticated ESPHome session unavailable")
        existing = self._bindings.get(satellite.entity_id)
        if existing is not None:
            old_connection, old_binding = existing
            if old_connection is connection:
                return old_binding
            old_binding.close()
            self._drop_conversation(satellite.entity_id, old_connection)
            self._removers.pop(satellite.entity_id)()
        binding = self.ingress.register_transport(
            satellite.entity_id, connection, connection_is_current=current,
        )
        self._bindings[satellite.entity_id] = connection, binding
        self._connection_checks[satellite.entity_id] = current

        def disconnected():
            # HA clears its disconnect callbacks on disconnect. Retain the hook,
            # so a future authenticated connection can get a fresh binding.
            binding.close()
            self._drop_conversation(satellite.entity_id, connection)
            followup = self._followups.pop(satellite.entity_id, None)
            if followup is not None:
                followup.cancel()
            for task in tuple(self._tasks):
                if self._tasks[task] is satellite:
                    task.cancel()

        runtime.disconnect_callbacks.add(disconnected)
        self._removers[satellite.entity_id] = lambda: runtime.disconnect_callbacks.discard(
            disconnected,
        )
        if not current(connection):
            disconnected()
            raise ValueError("ESPHome session closed during registration")
        return binding

    async def _accept(self, satellite, audio, start, end, wake_word, context):
        task = asyncio.current_task()
        self._tasks[task] = satellite
        try:
            if (
                self._closed or start is not PipelineStage.STT or end is not PipelineStage.TTS
                or satellite._ask_question_future is not None
                or satellite._wake_word_intercept_future is not None
                or any(other is not task and entity is satellite
                       for other, entity in self._tasks.items())
            ):
                raise ValueError("Unsupported protected pipeline invocation")
            binding = self._binding(satellite)
            connection = self._bindings[satellite.entity_id][0]
            state = self._conversation(satellite.entity_id, connection)
            await self._history.async_load()
            # Some devices request the new pipeline before delivering the playback
            # finished callback. Their transition into a follow-up pipeline is the
            # fallback listening boundary; it never carries speaker authority.
            if state.pending_speech:
                self._arm_window(satellite)
            pipeline = async_get_pipeline(self.hass, satellite._resolve_pipeline())
            agent = conversation.async_get_agent(self.hass, pipeline.conversation_engine)
            if not isinstance(agent, self._agent_type) or agent.entry is not self.entry:
                raise ValueError("Pipeline does not belong to this Codex entry")
            registry = er.async_get(self.hass).async_get(pipeline.stt_engine)
            if (
                registry is None or registry.platform != "codex_assist"
                or registry.config_entry_id != self.entry.entry_id
                or registry.disabled_by is not None
            ):
                raise ValueError("Protected pipeline requires this entry's paired STT")
            original = context if context is not None else Context()
            if not isinstance(original, Context):
                raise ValueError("Invalid original context")
            satellite.async_set_context(original)
            satellite._extra_system_prompt = None
            satellite._conversation_id = None
            satellite._run_has_tts = False
            pending = None
            followup = None
            from .protected_history import channel_digest, is_digest

            binding_id = channel_digest(
                self.entry.entry_id, satellite.entity_id,
                self._registry_identity(satellite.registry_entry),
            )
            channel = channel_digest(pipeline.id, pipeline.conversation_engine, pipeline.language)

            async def handler(payload, ctx, text, language):
                nonlocal pending, followup
                # Automatic silent follow-up capture is not a new user request.
                # Actual admitted STT, including stop/forget, invalidates old speech.
                old_followup = self._followups.pop(satellite.entity_id, None)
                if old_followup is not None:
                    old_followup.cancel()
                if state.deadline is not None and time.monotonic() > state.deadline:
                    state.clear()
                    return {"status": "denied", "completed": 0}, "This listening window ended."
                if is_stop_phrase(text):
                    state.clear()
                    return {"status": "completed", "completed": 0}, "Okay."
                subject = payload.get("continuation_identity")
                view = payload.get("continuation_view")
                if not is_digest(subject):
                    return {"status": "denied", "completed": 0}, "This request is not authorised."
                if is_forget_phrase(text):
                    pending = ("forget", view)
                    return (
                        {"status": "completed", "completed": 0},
                        "Okay, I've cleared the conversation context available to you.",
                    )
                history, candidates = self._history.previous(
                    satellite.entity_id, binding_id, channel, view,
                )
                payload["history"] = history
                payload["participant"] = f"Participant {subject[:12]}"
                from .guest_control import GuestMusicControlTool

                music = next((tool for tool in payload["tools"]
                              if isinstance(tool, GuestMusicControlTool)), None)
                if music is not None:
                    music.restore_continuation_candidates(candidates)
                    music.consume_saved_choices = lambda: self._history.async_consume_choices(
                        satellite.entity_id, binding_id,
                    )
                result, reply = await async_entry_voice_handler(
                    self.hass, self.entry, agent.profile, payload, ctx, text, language,
                )
                followup = payload
                dialogue = payload.get("turn_dialogue", [
                    {"role": "user", "content": str(text)},
                    {"role": "assistant", "content": reply},
                ])
                pending = (
                    "append", subject, view, dialogue,
                    music.continuation_candidates() if music is not None else {},
                )
                return result, reply

            async def accepted(result):
                if result.get("status") == "completed" and pending is not None:
                    if pending[0] == "forget":
                        await self._history.async_forget(
                            satellite.entity_id, binding_id, channel, pending[1],
                        )
                        state.clear()
                    elif await self._history.async_append(
                        satellite.entity_id, binding_id, channel, *pending[1:],
                    ):
                        state.reply_ready()
                    else:
                        state.clear()
                else:
                    state.clear()

            async def observed_audio():
                activity = SpeechActivity() if state.deadline is not None else None
                async for chunk in audio:
                    if activity is not None and state.deadline is not None:
                        if activity.process(chunk):
                            state.note_speech()
                    yield chunk

            result = await async_run_protected_pipeline(
                self.hass, pipeline=pipeline, context=original, audio_stream=observed_audio(),
                event_callback=satellite._internal_on_pipeline_event,
                binding=binding, ingress=self.ingress, handler=handler,
                device_id=satellite.registry_entry.device_id,
                satellite_id=satellite.entity_id, tts_audio_output=satellite.tts_options,
                wake_word_phrase=wake_word,
                silence_seconds=satellite._resolve_vad_sensitivity(),
                on_result=accepted, should_continue=lambda: state.pending_speech,
                on_speech=state.note_speech,
            )
            if not isinstance(result, dict) or result.get("status") != "completed":
                state.clear()
            elif followup is not None:
                self._start_followup(satellite, connection, state, followup)
        except asyncio.CancelledError:
            self._drop_conversation(satellite.entity_id)
            raise
        except Exception:
            self._drop_conversation(satellite.entity_id)
            satellite._internal_on_pipeline_event(PipelineEvent(PipelineEventType.ERROR, {
                "code": "protected-satellite-denied",
                "message": "Protected voice routing is unavailable.",
            }))
            satellite._internal_on_pipeline_event(PipelineEvent(PipelineEventType.RUN_END))
        finally:
            self._tasks.pop(task, None)

    def _start_followup(self, satellite, connection, state, payload):
        """Report only this turn's failed feedback, after its native TTS finishes."""
        from .action_followup import async_failure_followup

        checks = payload.get("device_checks")
        read = payload.get("followup_read")
        reply = payload.get("failure_reply")
        if checks is None or not checks.targets or not callable(read) or not callable(reply):
            return
        eid = satellite.entity_id
        binding = self._bindings.get(eid)
        connection_current = self._connection_checks.get(eid)
        if binding is None or binding[0] is not connection or not callable(connection_current):
            return

        def current():
            try:
                return (
                    not self._closed and self.entry.options is self._options
                    and self._entity(eid) is satellite and satellite.available
                    and self._bindings.get(eid) is binding
                    and self._connection_checks.get(eid) is connection_current
                    and connection_current(connection) is True
                    and satellite.cli._connection is connection and connection.is_connected
                    and self._followups.get(eid) is asyncio.current_task()
                )
            except Exception:
                return False

        def ready():
            return (
                not state.pending_speech and satellite.state == "idle"
                and not any(entity is satellite for entity in self._tasks.values())
            )

        async def announce(text):
            # This is the originating enrolled satellite, never an LLM destination.
            await satellite.async_internal_announce(message=text, preannounce=False)

        async def run():
            try:
                await async_failure_followup(
                    observe=lambda: checks.observe(self.hass, read), reply=reply,
                    current=current, ready=ready, announce=announce,
                )
            finally:
                if self._followups.get(eid) is asyncio.current_task():
                    self._followups.pop(eid, None)

        self._followups[eid] = self.entry.async_create_background_task(
            self.hass, run(), "codex-device-failure-followup", eager_start=False,
        )

    def close(self):
        """Revoke first. Restore only our exact hook, never a newer peer's hook."""
        self._closed = True
        for eid in tuple(self._conversations):
            self._drop_conversation(eid)
        tasks = set(self._tasks)
        tasks.update(self._followups.values())
        self._followups.clear()
        tasks.update(self.ingress.close())
        for task in tasks:
            if task is not asyncio.current_task():
                task.cancel()
        for remove in self._removers.values():
            remove()
        self._removers.clear()
        retained = self.entry.options.get(CONF_PROTECTED_SATELLITES, [])
        if self._constructor is not None:
            self._constructor.release(self, retained)
        for eid, (satellite, hook, previous) in self._hooks.items():
            if eid in retained:
                # Reload/unload is not permission to fall back to sentence triggers.
                # A replacement adapter may take over our exact closed hook.
                continue
            if satellite.__dict__.get(HOOK) is hook:
                if previous is None:
                    delattr(satellite, HOOK)
                else:
                    setattr(satellite, HOOK, previous)
                if self._guards.get(eid, (None,))[0] is self:
                    self._guards.pop(eid)
        for eid in tuple(self._completion_hooks):
            if eid not in retained:
                self._restore_completion_hook(eid)
        return tasks

    async def async_close(self):
        await asyncio.gather(*self.close(), return_exceptions=True)


def setup_entry_adapter(hass, entry):
    """Called only after explicit opt-in; leave all other entries untouched."""
    from homeassistant.exceptions import ConfigEntryNotReady

    approved = entry.options.get(CONF_PROTECTED_SATELLITES, [])
    if not approved:
        return
    if (
        type(approved) is not list or len(approved) > 32
        or any(type(eid) is not str or not eid.startswith("assist_satellite.")
               for eid in approved)
        or len(set(approved)) != len(approved)
    ):
        raise ConfigEntryNotReady("Invalid protected satellite enrollment")
    adapters = hass.data.setdefault(DATA_ADAPTERS, {})
    if entry.entry_id in adapters:
        raise ConfigEntryNotReady("Protected satellite adapter already loaded")
    adapter = None
    try:
        adapter = KioskSatelliteAdapter(hass, entry, approved)
        adapter.install()
    except Exception:
        if adapter is not None:
            adapter.close()
        raise ConfigEntryNotReady(
            "Protected satellite adapter unavailable; no ordinary Assist fallback",
        ) from None
    adapters[entry.entry_id] = adapter

    def unload():
        adapter.close()
        if adapters.get(entry.entry_id) is adapter:
            adapters.pop(entry.entry_id)

    entry.async_on_unload(unload)


async def async_stop_entry_adapter(hass, entry):
    """Await active audio/model/tool cancellation before platform unload."""
    adapter = hass.data.get(DATA_ADAPTERS, {}).get(entry.entry_id)
    if adapter is not None:
        await adapter.async_close()
