"""Real Core timers; mocked native ESPHome action boundary, not physical acceptance."""

import json
import sys
from dataclasses import replace
from types import ModuleType, SimpleNamespace

import pytest
from homeassistant.core import Context

from custom_components.codex_assist.satellite_runtime import satellite_tools_supported

if not satellite_tools_supported():
    pytest.skip("Modern satellite tools required", allow_module_level=True)

from aioesphomeapi import (
    ExecuteServiceResponse,
    SupportsResponseType,
    UserService,
    UserServiceArg,
    UserServiceArgType,
)
from homeassistant.components.intent.timers import TimerEventType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist import satellite_timer_targets as targets
from custom_components.codex_assist.guest_control import async_guest_tools
from custom_components.codex_assist.satellite_timers import SatelliteTimerTool
from tests_ha.test_satellite_timers import invoke
from tests_ha.test_satellite_timers import timers as timers


@pytest.fixture
async def fleet(hass, timers, monkeypatch):
    e = timers
    state = SimpleNamespace(
        satellites={}, read=set(), control=set(), enrolled=[], calls=[], contexts=[],
        query_hook=None, fail=set(), stuck=set(),
    )
    async def execute(runtime, service, call, **kwargs):
        # External boundary only: native ESPHome's Bluetooth/USB dependencies are
        # not required by these tests. Core's TimerManager/registries are real.
        state.contexts.append(call.context)
        assert call.return_response and kwargs["supports_response"] == service.supports_response
        response = await runtime.client.execute_service(service, call.data, return_response=True)
        if not response.success:
            raise ValueError("Synthetic action failure")
        return json.loads(response.response_data) if response.response_data else None

    native = ModuleType("homeassistant.components.esphome.manager")
    native.execute_service = execute
    monkeypatch.setitem(sys.modules, native.__name__, native)

    class Client:
        is_connected = True
        noise_psk = "synthetic-not-a-credential"

        def __init__(self, eid):
            self.eid, self.rows = eid, {}

        async def execute_service(self, service, data, *, return_response):
            assert return_response
            state.calls.append((self.eid, service.name, dict(data)))
            if self.eid in state.fail:
                raise TimeoutError("Synthetic unavailable target")
            if service.name == "vs_list_timers":
                result = {"timers": list(self.rows.values())}
                if state.query_hook:
                    state.query_hook(self.eid)
            else:
                assert service.name == "vs_cancel_timer" and set(data) == {"timer_id"}
                assert data["timer_id"]
                if self.eid not in state.stuck:
                    self.rows.pop(data["timer_id"], None)
                result = {"success": True}
            return ExecuteServiceResponse(
                success=True, response_data=json.dumps(result).encode(),
            )

    class Satellite:
        available = True

        def __init__(self, entry, registry_entry):
            self.config_entry, self.registry_entry = entry, registry_entry
            self.entity_id = registry_entry.entity_id
            self.cli = entry.runtime_data.client

        def handle_timer_event(self, event, timer):
            rows = self.cli.rows
            if event == TimerEventType.CANCELLED:
                rows.pop(timer.id, None)
            else:
                rows[timer.id] = {
                    "timer_id": timer.id, "name": timer.name or "",
                    "total_seconds": sum((timer.start_hours or 0,)) * 3600
                    + (timer.start_minutes or 0) * 60 + (timer.start_seconds or 0),
                    "seconds_left": timer.seconds_left, "is_active": timer.is_active,
                    "finished": event == TimerEventType.FINISHED, "ends_at": None,
                }

    for index, label in enumerate(("Kitchen", "Office", "Bedroom")):
        if index == 0:
            registry_entry = e.satellite
            entry = hass.config_entries.async_get_entry(registry_entry.config_entry_id)
        else:
            entry = MockConfigEntry(domain="esphome")
            entry.add_to_hass(hass)
            device = dr.async_get(hass).async_get_or_create(
                config_entry_id=entry.entry_id, identifiers={("esphome", label)},
            )
            registry_entry = er.async_get(hass).async_get_or_create(
                "assist_satellite", "esphome", label, config_entry=entry, device_id=device.id,
            )
        area = ar.async_get(hass).async_create(label, aliases={label + " room"})
        registry_entry = er.async_get(hass).async_update_entity(
            registry_entry.entity_id, name=label + " screen", area_id=area.id,
        )
        services = [
            UserService(name="vs_list_timers", key=1,
                        supports_response=SupportsResponseType.OPTIONAL),
            UserService(name="vs_cancel_timer", key=2, args=[
                UserServiceArg(name="timer_id", type=UserServiceArgType.STRING),
            ], supports_response=SupportsResponseType.OPTIONAL),
        ]
        entry.runtime_data = SimpleNamespace(
            available=True, client=Client(registry_entry.entity_id),
            services={service.key: service for service in services},
            name="synthetic-node",
        )
        satellite = Satellite(entry, registry_entry)
        state.satellites[satellite.entity_id] = satellite
        state.read.add(satellite.entity_id)
        state.control.add(satellite.entity_id)
        state.enrolled.append(satellite.entity_id)
        hass.states.async_set(satellite.entity_id, "idle")
        e.manager.register_handler(registry_entry.device_id, satellite.handle_timer_event)
    monkeypatch.setattr(targets, "_component", lambda _: SimpleNamespace(
        get_entity=state.satellites.get,
    ))

    async def permitted(_hass, auth, eid, *, action="read"):
        return auth.valid() and eid in (state.read if action == "read" else state.control)

    monkeypatch.setattr(targets, "async_timer_access", permitted)

    async def permitted_batch(_hass, auth, eids, *, action="read"):
        return all([await permitted(_hass, auth, eid, action=action) for eid in eids])

    monkeypatch.setattr(targets, "async_timer_access_batch", permitted_batch)

    async def tool():
        result = SatelliteTimerTool(hass, e.auth)
        result.validate_references = e.policy
        result.remote_targets = await targets.TimerTargets.async_create(
            hass, e.auth, tuple(state.enrolled), lambda: state.enrolled,
        )
        return result

    def start(eid, *, name="Tea", minutes=10, finished=False):
        device_id = state.satellites[eid].registry_entry.device_id
        timer_id = e.manager.start_timer(device_id, None, minutes, None, "en", name=name)
        if finished:
            e.manager.timer_tasks[timer_id].cancel()
            e.manager._timer_finished(timer_id)
        return timer_id

    yield SimpleNamespace(
        e=e, state=state, tool=tool, start=start,
        kitchen=state.enrolled[0], office=state.enrolled[1], bedroom=state.enrolled[2],
    )
    assert all(context is e.context for context in state.contexts)


def cancellations(fleet):
    return [call for call in fleet.state.calls if call[1] == "vs_cancel_timer"]


def set_text(fleet, text):
    """Simulate a fresh admitted utterance, not another model proposal in the same turn."""
    prepared = replace(fleet.e.prepared, text=text)
    fleet.e.auth = replace(
        fleet.e.auth, prepared=prepared,
        request_is_current=lambda ctx, req: (
            fleet.e.state.current and ctx is fleet.e.context and req is prepared
        ),
    )


async def test_automatic_stop_uses_only_uniquely_reported_alert_on_another_satellite(hass, fleet):
    f = fleet
    running = f.start(f.kitchen, name="Pasta")
    ringing = f.start(f.office, finished=True)
    result = await invoke(hass, f.e, {"action": "stop"}, tool=await f.tool())
    assert not result.error, (result.data, f.state.calls)
    assert result.data["timer_action"] == "cancelled"
    assert result.data["satellite"] == "Office screen"
    assert cancellations(f) == [(f.office, "vs_cancel_timer", {"timer_id": ringing})]
    assert set(f.e.manager.timers) == {running}


async def test_multiple_alerts_require_clarification_not_nearest_or_first(hass, fleet):
    for eid in (fleet.office, fleet.bedroom):
        fleet.start(eid, finished=True)
    result = await invoke(hass, fleet.e, {"action": "stop"}, tool=await fleet.tool())
    assert result.data["status"] == "clarification_required"
    assert cancellations(fleet) == []


async def test_zero_remaining_time_is_not_ringing_evidence(hass, fleet):
    timer_id = fleet.start(fleet.office)
    fleet.state.satellites[fleet.office].cli.rows[timer_id].update(
        seconds_left=0, is_active=False, finished=False,
    )
    result = await invoke(hass, fleet.e, {"action": "stop"}, tool=await fleet.tool())
    assert result.error
    assert cancellations(fleet) == []
    assert timer_id in fleet.e.manager.timers


async def test_explicit_room_cancel_uses_exact_native_id_not_firmware_name_fallback(hass, fleet):
    timer_id = fleet.start(fleet.office)
    other = fleet.start(fleet.bedroom)
    set_text(fleet, "Cancel the Tea timer in the Office room")
    result = await invoke(
        hass, fleet.e, {"action": "cancel", "satellite": "Office room", "name": "Tea"},
        tool=await fleet.tool(),
    )
    assert result.data["timer_action"] == "cancelled"
    assert set(fleet.e.manager.timers) == {other}
    assert timer_id not in fleet.e.manager.timers
    assert cancellations(fleet) == []


async def test_read_only_target_alert_is_never_queried_or_cancelled_automatically(hass, fleet):
    fleet.start(fleet.office, finished=True)
    fleet.state.control.remove(fleet.office)
    result = await invoke(hass, fleet.e, {"action": "stop"}, tool=await fleet.tool())
    assert result.error
    assert all(call[0] != fleet.office for call in fleet.state.calls)
    assert cancellations(fleet) == []


async def test_explicit_read_only_target_cancel_denies_without_effect(hass, fleet):
    timer_id = fleet.start(fleet.office)
    fleet.state.control.remove(fleet.office)
    set_text(fleet, "Cancel the timer in the Office")
    result = await invoke(
        hass, fleet.e, {"action": "cancel", "satellite": "Office"}, tool=await fleet.tool(),
    )
    assert result.error
    assert timer_id in fleet.e.manager.timers


async def test_alert_query_failure_does_not_choose_another_targets_only_visible_alert(hass, fleet):
    fleet.start(fleet.office, finished=True)
    fleet.state.fail.add(fleet.bedroom)
    result = await invoke(hass, fleet.e, {"action": "stop"}, tool=await fleet.tool())
    assert result.error
    assert cancellations(fleet) == []


async def test_unknown_target_never_falls_back_to_current_satellite(hass, fleet):
    timer_id = fleet.start(fleet.kitchen)
    result = await invoke(
        hass, fleet.e, {"action": "cancel", "satellite": "Unrelated room"},
        tool=await fleet.tool(),
    )
    assert result.data["status"] == "clarification_required"
    assert timer_id in fleet.e.manager.timers
    assert fleet.state.calls == []


async def test_cancel_all_is_local_by_default_and_wider_only_with_explicit_scope(hass, fleet):
    local = fleet.start(fleet.kitchen)
    other = fleet.start(fleet.office)
    result = await invoke(hass, fleet.e, {"action": "cancel_all"}, tool=await fleet.tool())
    assert result.data["completed"] == 1
    assert local not in fleet.e.manager.timers and other in fleet.e.manager.timers
    set_text(fleet, "Cancel all timers everywhere")
    result = await invoke(
        hass, fleet.e, {"action": "cancel_all", "scope": "all_permitted"}, tool=await fleet.tool(),
    )
    assert result.data["completed"] == 1
    assert not fleet.e.manager.timers


async def test_model_cannot_silently_widen_cancel_all_scope(hass, fleet):
    timer_id = fleet.start(fleet.office)
    result = await invoke(
        hass, fleet.e, {"action": "cancel_all", "scope": "all_permitted"},
        tool=await fleet.tool(),
    )
    assert result.error
    assert timer_id in fleet.e.manager.timers
    assert cancellations(fleet) == []


async def test_source_list_reports_actual_alerts_not_retained_ended_objects(hass, fleet):
    timer_id = fleet.start(fleet.kitchen, finished=True)
    result = await invoke(hass, fleet.e, {"action": "list"}, tool=await fleet.tool())
    assert result.data["timers"][0]["state"] == "alerting"
    fleet.state.satellites[fleet.kitchen].cli.rows.pop(timer_id)
    result = await invoke(hass, fleet.e, {"action": "list"}, tool=await fleet.tool())
    assert result.data["timers"] == []


async def test_positive_response_without_alert_disappearance_is_not_spoken_as_success(hass, fleet):
    fleet.start(fleet.office, finished=True)
    fleet.state.stuck.add(fleet.office)
    result = await invoke(hass, fleet.e, {"action": "stop"}, tool=await fleet.tool())
    assert result.error
    assert result.data["completed"] == 1, fleet.state.calls
    assert len(cancellations(fleet)) == 1


async def test_permission_revocation_after_query_prevents_dismissal(hass, fleet):
    fleet.start(fleet.office, finished=True)
    fleet.state.query_hook = lambda eid: fleet.state.control.discard(eid)
    result = await invoke(hass, fleet.e, {"action": "stop"}, tool=await fleet.tool())
    assert result.error
    assert cancellations(fleet) == []


async def test_client_replacement_during_query_revokes_target(hass, fleet):
    fleet.start(fleet.office, finished=True)

    def replace(eid):
        if eid == fleet.office:
            satellite = fleet.state.satellites[eid]
            satellite.config_entry.runtime_data.client = object()

    fleet.state.query_hook = replace
    result = await invoke(hass, fleet.e, {"action": "stop"}, tool=await fleet.tool())
    assert result.error
    assert cancellations(fleet) == []


async def test_forged_foreign_core_timer_id_in_target_response_is_never_cancelled(hass, fleet):
    timer_id = fleet.start(fleet.bedroom)
    foreign = fleet.state.satellites[fleet.bedroom].cli.rows[timer_id]
    fleet.state.satellites[fleet.office].cli.rows[timer_id] = dict(foreign)
    set_text(fleet, "Cancel the timer in the Office")
    result = await invoke(
        hass, fleet.e, {"action": "cancel", "satellite": "Office"}, tool=await fleet.tool(),
    )
    assert result.error
    assert timer_id in fleet.e.manager.timers
    assert cancellations(fleet) == []


async def test_unenrolled_satellite_is_not_discovered_even_if_policy_would_allow_it(hass, fleet):
    fleet.start(fleet.bedroom, finished=True)
    fleet.state.enrolled.remove(fleet.bedroom)
    result = await invoke(hass, fleet.e, {"action": "stop"}, tool=await fleet.tool())
    assert result.error
    assert all(eid != fleet.bedroom for eid, *_ in fleet.state.calls)


async def test_remote_visibility_is_in_history_dependencies_and_rechecked(hass, fleet):
    payload = await async_guest_tools(
        hass, fleet.e.auth, fleet.e.ids, timer_satellite_ids=tuple(fleet.state.enrolled),
        timer_satellites_current=lambda: fleet.state.enrolled,
    )
    tool = next(t for t in payload["tools"] if t.name == SatelliteTimerTool.name)
    original = set(payload["continuation_view"])
    assert set(tool.remote_targets.view) <= original
    assert await payload["validate"]()
    fleet.state.read.remove(fleet.office)
    assert not await payload["validate"]()
    new = await async_guest_tools(
        hass, fleet.e.auth, fleet.e.ids, timer_satellite_ids=tuple(fleet.state.enrolled),
        timer_satellites_current=lambda: fleet.state.enrolled,
    )
    assert not original <= set(new["continuation_view"])


async def test_enrollment_change_after_tool_creation_revokes_catalogue(hass, fleet):
    tool = await fleet.tool()
    fleet.state.enrolled.remove(fleet.office)
    assert not await tool.remote_targets.current()


async def test_unsupported_permitted_reporter_blocks_automatic_guess_but_not_explicit_target(
    hass, fleet,
):
    ringing = fleet.start(fleet.office, finished=True)
    fleet.state.satellites[fleet.bedroom].config_entry.runtime_data.services.clear()
    tool = await fleet.tool()
    assert fleet.bedroom in tool.remote_targets.unobserved
    result = await invoke(hass, fleet.e, {"action": "stop"}, tool=tool)
    assert result.error
    assert cancellations(fleet) == []
    set_text(fleet, "Stop the timer in the Office")
    result = await invoke(
        hass, fleet.e, {"action": "stop", "satellite": "Office"}, tool=await fleet.tool(),
    )
    assert not result.error
    assert cancellations(fleet)[0][-1] == {"timer_id": ringing}


async def test_model_cannot_name_a_destination_to_bypass_automatic_ambiguity(hass, fleet):
    fleet.start(fleet.office, finished=True)
    fleet.start(fleet.bedroom, finished=True)
    set_text(fleet, "Stop the timer that is going off")
    tool = await fleet.tool()
    result = await invoke(
        hass, fleet.e, {"action": "stop", "satellite": "Office"}, tool=tool,
    )
    assert result.error
    assert cancellations(fleet) == []
    result = await invoke(hass, fleet.e, {"action": "stop"}, tool=tool)
    assert result.data["status"] == "clarification_required"
    # Another model call is not a fresh user answer, even if it supplies an alias.
    result = await invoke(
        hass, fleet.e, {"action": "cancel", "satellite": "Office"}, tool=tool,
    )
    assert result.error
    assert cancellations(fleet) == []


async def test_remote_context_is_revalidated_before_the_model_sees_it(hass, fleet):
    from custom_components.codex_assist.protected_model import async_fixed_tool_turn

    payload = await async_guest_tools(
        hass, fleet.e.auth, fleet.e.ids, timer_satellite_ids=tuple(fleet.state.enrolled),
        timer_satellites_current=lambda: fleet.state.enrolled,
    )
    assert callable(payload["timer_validate"])
    fleet.state.read.remove(fleet.office)

    class Client:
        async def stream_turn(self, **kwargs):
            raise AssertionError("Revoked remote context must not reach the model")
            yield  # pragma: no cover -- keep the external interface an async iterator

    result, _speech = await async_fixed_tool_turn(
        hass, Client(), SimpleNamespace(), payload, fleet.e.context, "List timers", "en",
    )
    assert result == {"status": "denied", "completed": 0}
    assert fleet.state.calls == []


async def test_metadata_changes_during_last_policy_await_revoke_the_catalogue(
    hass, fleet, monkeypatch,
):
    tool = await fleet.tool()

    async def rename(*args, **kwargs):
        er.async_get(hass).async_update_entity(fleet.office, name="Changed private label")
        return True

    monkeypatch.setattr(targets, "async_timer_access_batch", rename)
    assert not await tool.remote_targets.current()


@pytest.mark.parametrize("data", [
    {"timers": "not a list"}, {"timers": [None]}, {"timers": [{}]},
    {"timers": [], "instructions": "ignored"}, {"timers": [dict(
        timer_id="x", name="bad\nname", total_seconds=1, seconds_left=0,
        is_active=False, finished=True,
    )]},
])
async def test_malformed_device_timer_data_fails_closed(hass, fleet, monkeypatch, data):
    target = (await fleet.tool()).remote_targets.source

    async def response(*args):
        return data

    monkeypatch.setattr(target, "_call", response)
    with pytest.raises(ValueError):
        await target.query(hass, Context())
