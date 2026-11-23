"""Real HA HTTP authentication and TimerManager, simulated finite policy boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.components.intent.const import TIMER_DATA
from homeassistant.components.intent.timers import TimerManager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist.satellite_runtime import satellite_tools_supported

if not satellite_tools_supported():
    pytest.skip("Exact-ID kiosk HTTP controls require modern satellite support",
                allow_module_level=True)

from custom_components.codex_assist import timer_http


@pytest.fixture
async def exact(hass, hass_client, monkeypatch):
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "http", {})
    user = await hass.auth.async_create_user("Timer account", group_ids=[GROUP_ID_USER])
    refresh = await hass.auth.async_create_refresh_token(user, client_id="https://test.invalid")
    esphome = MockConfigEntry(domain="esphome")
    esphome.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=esphome.entry_id, identifiers={("esphome", "exact-timers")},
    )
    satellite = er.async_get(hass).async_get_or_create(
        "assist_satellite", "esphome", "exact-timers", config_entry=esphome,
        device_id=device.id,
    )
    hass.states.async_set(satellite.entity_id, "idle")
    async_expose_entity(hass, "conversation", satellite.entity_id, True)
    entry = MockConfigEntry(
        domain="codex_assist", state=ConfigEntryState.LOADED,
        options={"protected_satellite_ids": [satellite.entity_id]},
    )
    entry.add_to_hass(hass)
    remove = timer_http.register_timer_api(hass, entry)
    events = []
    manager = hass.data[TIMER_DATA] = TimerManager(hass)
    manager.register_handler(device.id, lambda *args: events.append(args))
    state = SimpleNamespace(allow=True, hook=None)

    async def policy(_hass, ids, *, action, user_id):
        assert _hass is hass and ids == (satellite.entity_id,)
        assert action in timer_http.ACTIONS and user_id == user.id
        if state.hook:
            state.hook()
        return SimpleNamespace(allowed=state.allow)

    provider = SimpleNamespace(
        TIMER_CONTROL_POLICY_VERSION=1, async_check_timer_control_access=AsyncMock(
            side_effect=policy,
        ),
    )
    monkeypatch.setattr(timer_http, "_provider", lambda: provider)
    client = await hass_client(hass.auth.async_create_access_token(refresh))

    async def command(timer_id, action, *, nonce=None, **extra):
        if nonce is None:
            discovery = await client.get(timer_http.URL)
            assert discovery.status == 200
            nonce = (await discovery.json())["nonce"]
        return await client.post(timer_http.URL, json={
            "entity_id": satellite.entity_id, "timer_id": timer_id,
            "action": action, "nonce": nonce, **extra,
        })

    def start(name="Tea", device_id=device.id, delayed=None):
        return manager.start_timer(
            device_id, None, 10, None, "en", name=name, conversation_command=delayed,
        )

    yield SimpleNamespace(
        client=client, command=command, start=start, entry=entry, satellite=satellite,
        device=device, manager=manager, provider=provider, state=state, events=events,
        api=hass.data[timer_http.DATA_API], remove=remove, user=user,
    )
    remove()
    for task in manager.timer_tasks.values():
        task.cancel()


@pytest.mark.parametrize("name", ["Tea", None])
@pytest.mark.parametrize("action", ["pause", "resume", "cancel", "add", "remove"])
async def test_identical_named_or_unnamed_timers_change_only_the_exact_selected_id(
    hass, exact, name, action,
):
    e = exact
    first, selected = e.start(name), e.start(name)
    timer = e.manager.timers[selected]
    if action == "resume":
        e.manager.pause_timer(selected)
    e.events.clear()
    result = await e.command(
        selected, action, **({"seconds": 30} if action in {"add", "remove"} else {}),
    )
    assert result.status == 200, await result.text()
    assert await result.json() == {
        "api": timer_http.API, "version": 1, "status": "accepted",
        "timer_id": selected, "action": action,
    }
    assert e.manager.timers[first].is_active
    assert e.manager.timers[first].seconds_left == 600
    assert len(e.events) == 1 and e.events[0][1] is timer
    if action == "cancel":
        assert selected not in e.manager.timers
    elif action in {"pause", "resume"}:
        assert timer.is_active is (action == "resume")
    else:
        assert timer.seconds_left == (630 if action == "add" else 570)


async def test_another_devices_timer_or_delayed_command_is_never_targeted(hass, exact):
    e = exact
    e.manager.register_handler("other-device", lambda *_: None)
    for timer_id in (
        e.start(device_id="other-device"),
        e.start(delayed="turn on something later"),
    ):
        result = await e.command(timer_id, "cancel")
        assert result.status == 404
        assert timer_id in e.manager.timers
    result = await e.command("does-not-exist", "cancel")
    assert result.status == 404


async def test_operation_nonce_is_one_use_and_not_an_automatic_retry_token(exact):
    e = exact
    timer_id = e.start()
    nonce = (await (await e.client.get(timer_http.URL)).json())["nonce"]
    assert (await e.command(timer_id, "add", nonce=nonce, seconds=30)).status == 200
    assert (await e.command(timer_id, "add", nonce=nonce, seconds=30)).status == 409
    assert e.manager.timers[timer_id].seconds_left == 630


async def test_denied_nonce_cannot_be_replayed_after_permissions_change(exact):
    e = exact
    timer_id = e.start()
    nonce = (await (await e.client.get(timer_http.URL)).json())["nonce"]
    e.state.allow = False
    assert (await e.command(timer_id, "cancel", nonce=nonce)).status == 403
    e.state.allow = True
    assert (await e.command(timer_id, "cancel", nonce=nonce)).status == 409
    assert timer_id in e.manager.timers


async def test_pause_resume_noops_and_zero_clamped_adjustment_stay_exact(exact):
    e = exact
    first, selected = e.start(), e.start()
    e.events.clear()
    assert (await e.command(selected, "resume")).status == 200
    assert not e.events
    assert (await e.command(selected, "pause")).status == 200
    e.events.clear()
    assert (await e.command(selected, "pause")).status == 200
    assert not e.events
    assert (await e.command(selected, "remove", seconds=601)).status == 200
    # Core preserves a paused zero-duration timer until it is resumed.
    assert e.manager.timers[selected].seconds_left == 0
    assert not e.manager.timers[selected].is_active
    assert e.manager.timers[first].is_active
    assert e.manager.timers[first].seconds_left == 600


async def test_stale_unload_callback_cannot_remove_new_enrollment(exact, hass):
    e = exact
    timer_id = e.start()
    remove_new = timer_http.register_timer_api(hass, e.entry)
    e.remove()
    assert (await e.command(timer_id, "pause")).status == 200
    remove_new()
    assert (await e.client.get(timer_http.URL)).status == 503


async def test_operation_nonce_is_bound_to_the_authenticated_account(
    exact, hass, hass_client, hass_admin_user,
):
    e = exact
    timer_id = e.start()
    nonce = (await (await e.client.get(timer_http.URL)).json())["nonce"]
    refresh = await hass.auth.async_create_refresh_token(
        hass_admin_user, client_id="https://test.invalid",
    )
    other_client = await hass_client(hass.auth.async_create_access_token(refresh))
    result = await other_client.post(timer_http.URL, json={
        "entity_id": e.satellite.entity_id, "timer_id": timer_id,
        "action": "cancel", "nonce": nonce,
    })
    assert result.status == 409
    e.provider.async_check_timer_control_access.assert_not_awaited()
    assert timer_id in e.manager.timers
    assert (await e.command(timer_id, "cancel", nonce=nonce)).status == 200


@pytest.mark.parametrize("extra", [
    {"user_id": "owner"}, {"guest_role_id": "guest"}, {"name": "Tea"}, {"seconds": True},
    {"seconds": -1}, {"action": "cancel_all"}, {"timer_id": ""},
    {"entity_id": "light.test"}, {"action": ["cancel"]},
])
async def test_malformed_or_identity_override_payload_is_not_a_control_grant(exact, extra):
    timer_id = exact.start()
    nonce = (await (await exact.client.get(timer_http.URL)).json())["nonce"]
    result = await exact.client.post(timer_http.URL, json={
        "entity_id": exact.satellite.entity_id, "timer_id": timer_id,
        "action": "add", "seconds": 30, "nonce": nonce, **extra,
    })
    assert result.status == 400
    assert exact.manager.timers[timer_id].seconds_left == 600
    exact.provider.async_check_timer_control_access.assert_not_awaited()


async def test_unauthenticated_request_is_rejected_by_home_assistant(exact, hass_client_no_auth):
    client = await hass_client_no_auth()
    assert (await client.get(timer_http.URL)).status == 401
    assert (await client.post(timer_http.URL, json={})).status == 401


async def test_policy_denial_never_becomes_fallback_or_a_guest_request(exact):
    timer_id = exact.start()
    exact.state.allow = False
    result = await exact.command(timer_id, "cancel")
    assert result.status == 403
    assert timer_id in exact.manager.timers
    assert not any(event[0].value == "cancelled" for event in exact.events)


@pytest.mark.parametrize("change", [
    "entry_options", "unload", "identity", "manager", "handler", "timer", "duplicate_owner",
])
async def test_lifecycle_registry_and_timer_changes_during_policy_await_deny(
    exact, hass, change,
):
    e = exact
    timer_id = e.start()

    def mutate():
        if change == "entry_options":
            hass.config_entries.async_update_entry(e.entry, options={})
        elif change == "unload":
            e.remove()
        elif change == "identity":
            er.async_get(hass).async_update_entity(e.satellite.entity_id, name="Changed")
        elif change == "manager":
            hass.data[TIMER_DATA] = TimerManager(hass)
        elif change == "handler":
            e.manager.handlers[e.device.id] = lambda *_: None
        elif change == "timer":
            e.manager.cancel_timer(timer_id)
        else:
            other = MockConfigEntry(
                domain="codex_assist", state=ConfigEntryState.LOADED,
                options=dict(e.entry.options),
            )
            other.add_to_hass(hass)
            timer_http.register_timer_api(hass, other)
        e.events.clear()

    e.state.hook = mutate
    result = await e.command(timer_id, "cancel")
    assert result.status in {403, 404}
    assert not e.events


async def test_unloaded_route_stays_present_but_fails_closed(exact):
    exact.remove()
    result = await exact.client.get(timer_http.URL)
    assert result.status == 503
    assert (await result.json())["api"] == timer_http.API


async def test_provider_version_and_errors_do_not_widen_authority(exact):
    timer_id = exact.start()
    exact.provider.TIMER_CONTROL_POLICY_VERSION = True
    assert (await exact.command(timer_id, "cancel")).status == 503
    exact.provider.TIMER_CONTROL_POLICY_VERSION = 1
    exact.provider.async_check_timer_control_access.side_effect = TimeoutError()
    assert (await exact.command(timer_id, "cancel")).status == 503
    assert timer_id in exact.manager.timers


async def test_adjustments_are_bounded_and_failed_callbacks_cannot_be_replayed(exact):
    e = exact
    timer_id = e.start()
    assert (await e.command(timer_id, "add", seconds=timer_http.MAX_SECONDS)).status == 400
    calls = []

    def fail(*args):
        calls.append(args)
        raise RuntimeError("Synthetic callback failure after effect")

    e.manager.handlers[e.device.id] = fail
    nonce = (await (await e.client.get(timer_http.URL)).json())["nonce"]
    assert (await e.command(timer_id, "add", nonce=nonce, seconds=30)).status == 502
    assert (await e.command(timer_id, "add", nonce=nonce, seconds=30)).status == 409
    assert len(calls) == 1 and e.manager.timers[timer_id].seconds_left == 630


async def test_oversize_and_duplicate_keys_are_rejected(exact):
    e = exact
    assert (await e.client.post(
        timer_http.URL, data="x" * 5000, headers={"Content-Type": "application/json"},
    )).status == 413
    assert (await e.client.post(
        timer_http.URL, data='{"action":"pause","action":"cancel"}',
        headers={"Content-Type": "application/json"},
    )).status == 400


async def test_expired_nonce_or_capacity_does_not_grant_execution(exact, monkeypatch):
    e = exact
    timer_id = e.start()
    nonce = (await (await e.client.get(timer_http.URL)).json())["nonce"]
    e.api.nonces[nonce] = (e.user.id, 0)
    assert (await e.command(timer_id, "cancel", nonce=nonce)).status == 409
    monkeypatch.setattr(timer_http, "MAX_NONCES", 1)
    assert (await e.client.get(timer_http.URL)).status == 200
    assert (await e.client.get(timer_http.URL)).status == 429
    assert timer_id in e.manager.timers


async def test_real_paired_policy_and_proxy_catalogue_admit_only_explicit_target_rights(
    exact, hass, monkeypatch,
):
    provider = pytest.importorskip("custom_components.ha_rbac.assist_policy")
    from custom_components.ha_rbac.catalog import Catalog
    from custom_components.ha_rbac.const import DATA_RBAC, TIER_OPEN
    from custom_components.ha_rbac.decide import KIND_HTTP, Decider
    from custom_components.ha_rbac.filters import FilterRegistry
    from custom_components.ha_rbac.policy import Evaluator, default_roles

    e = exact
    store = SimpleNamespace(
        roles={**default_roles(), "timer_user": {
            "id": "timer_user", "name": "Timer user",
            "allow": {"entities": {"entity_ids": {
                e.satellite.entity_id: {"read": True, "control": True},
            }}},
        }},
        bindings={e.user.id: ["timer_user"]}, global_deny={},
    )
    evaluator = Evaluator(hass, store)
    hass.data[DATA_RBAC] = SimpleNamespace(store=store, evaluator=evaluator)
    monkeypatch.setattr(timer_http, "_provider", lambda: provider)
    catalog = Catalog(hass)
    catalog.rebuild()
    assert catalog.tier_for_request("POST", timer_http.URL) == TIER_OPEN
    decider = Decider(hass, catalog, FilterRegistry())
    assert decider.decide(
        evaluator.async_permissions(e.user), KIND_HTTP, "GET " + timer_http.URL, {},
    ).allowed
    # The actual endpoint's entity_id is a recognised proxy bound; no unbounded
    # Assist exemption, administrative role or catalogue exception is installed.
    assert decider.decide(
        evaluator.async_permissions(e.user), KIND_HTTP, "POST " + timer_http.URL,
        {"entity_id": e.satellite.entity_id, "timer_id": "some-id", "action": "pause"},
    ).allowed
    first, selected = e.start(), e.start()
    assert (await e.command(selected, "pause")).status == 200
    assert not e.manager.timers[selected].is_active and e.manager.timers[first].is_active
    store.roles["timer_user"]["allow"]["entities"]["entity_ids"][e.satellite.entity_id][
        "control"
    ] = False
    evaluator.invalidate()
    assert (await e.command(selected, "cancel")).status == 403
    assert selected in e.manager.timers
    assert not decider.decide(
        evaluator.async_permissions(e.user), KIND_HTTP, "POST " + timer_http.URL,
        {"entity_id": e.satellite.entity_id, "timer_id": selected, "action": "cancel"},
    ).allowed
