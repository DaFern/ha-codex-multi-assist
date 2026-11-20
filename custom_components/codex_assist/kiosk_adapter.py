"""Experimental opt-in ESPHome instance hooks with approved constructor interception.

Private HA/aioesphomeapi details are version-sensitive. An unsupported shape,
plaintext connection, changed registry/client/configuration or lost connection
denies the turn. This module never replaces an ESPHome entity or subscription.
"""

import asyncio
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

from .guest_policy import GUEST_DOMAINS
from .protected_model import async_entry_voice_handler
from .protected_pipeline import async_run_protected_pipeline
from .rbac_satellite import ProtectedSatelliteDispatcher

CONF_PROTECTED_SATELLITES = "protected_satellite_ids"
DATA_ADAPTERS = "codex_assist_protected_satellites"
DATA_GUARDS = "codex_assist_protected_guards"
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

        self.hass, self.entry = hass, entry
        self._agent_type = CodexAssistConversationEntity
        self._approved = frozenset(approved_satellite_ids)
        self._options = entry.options
        self._closed = False
        self._hooks = {}
        self._tasks = {}
        self._bindings = {}
        self._removers = {}
        self._enrollments = {}
        self._constructor = None
        self._guards = hass.data.setdefault(DATA_GUARDS, {})
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
            if state.domain in GUEST_DOMAINS
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
            self._removers.pop(satellite.entity_id)()
        binding = self.ingress.register_transport(
            satellite.entity_id, connection, connection_is_current=current,
        )
        self._bindings[satellite.entity_id] = connection, binding

        def disconnected():
            # HA clears its disconnect callbacks on disconnect. Retain the hook,
            # so a future authenticated connection can get a fresh binding.
            binding.close()
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

            async def handler(payload, ctx, text, language):
                return await async_entry_voice_handler(
                    self.hass, self.entry, agent.profile, payload, ctx, text, language,
                )

            await async_run_protected_pipeline(
                self.hass, pipeline=pipeline, context=original, audio_stream=audio,
                event_callback=satellite._internal_on_pipeline_event,
                binding=binding, ingress=self.ingress, handler=handler,
                device_id=satellite.registry_entry.device_id,
                satellite_id=satellite.entity_id, tts_audio_output=satellite.tts_options,
                wake_word_phrase=wake_word,
                silence_seconds=satellite._resolve_vad_sensitivity(),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            satellite._internal_on_pipeline_event(PipelineEvent(PipelineEventType.ERROR, {
                "code": "protected-satellite-denied",
                "message": "Protected voice routing is unavailable.",
            }))
            satellite._internal_on_pipeline_event(PipelineEvent(PipelineEventType.RUN_END))
        finally:
            self._tasks.pop(task, None)

    def close(self):
        """Revoke first. Restore only our exact hook, never a newer peer's hook."""
        self._closed = True
        tasks = set(self._tasks)
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
