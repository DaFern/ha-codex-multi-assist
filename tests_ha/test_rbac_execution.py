"""Inactive exact-target adapter tested against real native Assist/service code."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er

from custom_components.codex_assist import rbac_execution, rbac_policy
from custom_components.codex_assist.rbac_execution import SharedExecutionGuard
from custom_components.codex_assist.voice_match import PreparedRequest


def turn(owner="child"):
    return PreparedRequest("Private request", "", None, None, verified=True,
                           voice="profile", ha_user_id=owner)


@pytest.fixture
def env(hass, monkeypatch):
    registry = er.async_get(hass)
    for domain, name in (("light", "allowed"), ("light", "denied"), ("fan", "allowed")):
        registry.async_get_or_create(domain, "test", name, suggested_object_id=name)
        hass.states.async_set(f"{domain}.{name}", "off", {"friendly_name": "Duplicate name"})
    exposed = {"light.allowed", "light.denied", "fan.allowed"}
    monkeypatch.setattr(rbac_execution, "async_should_expose", lambda h, a, e: e in exposed)
    api = SimpleNamespace(API_VERSION=1, async_check_access=AsyncMock(
        side_effect=lambda h, u, ids, **kw: SimpleNamespace(allowed="light.denied" not in ids),
    ))
    monkeypatch.setattr(rbac_policy, "import_module", lambda name: api)
    calls = []

    async def record(call):
        calls.append((call.domain, call.service, dict(call.data), call.context))

    for domain in ("light", "fan"):
        for service in ("turn_on", "turn_off"):
            hass.services.async_register(domain, service, record)
    context = Context(user_id="kiosk")
    prepared = turn()
    guard = SharedExecutionGuard(hass, approved_kiosk_user_ids=frozenset({"kiosk"}))
    return SimpleNamespace(hass=hass, guard=guard, context=context, prepared=prepared,
                           api=api, calls=calls, exposed=exposed, registry=registry)


def prepare(env, ids=("light.allowed",), operation="turn_on", **kw):
    return env.guard.prepare(kw.get("context", env.context), kw.get("turn", env.prepared),
                             ids, operation=operation)


async def execute(env, command, **kw):
    return await env.guard.async_execute(command, context=kw.get("context", env.context),
                                         prepared_request=kw.get("turn", env.prepared))


@pytest.mark.parametrize("operation", ["turn_on", "turn_off"])
async def test_native_exact_targets_once_preserves_caller_and_rechecks_inside_tasks(env, operation):
    command = prepare(env, ("light.allowed", "fan.allowed"), operation)
    result = await execute(env, command)
    assert result.status == "completed" and result.completed == 2
    assert env.calls == [(domain, operation, {"entity_id": f"{domain}.allowed"}, env.context)
                         for domain in ("light", "fan")]
    assert env.api.async_check_access.await_count == 3  # Whole batch + each native task.
    for call in env.api.async_check_access.call_args_list:
        assert call.args[1:] == ("child", ("light.allowed", "fan.allowed"))
        assert call.kwargs == {"operation": operation, "attributes": (), "ceiling_user_id": "kiosk"}
    assert (await execute(env, command)).status == "denied"
    assert len(env.calls) == 2


@pytest.mark.parametrize("ids", [("light.denied",), ("light.allowed", "light.denied")])
async def test_forbidden_or_mixed_targets_execute_zero_commands(env, ids):
    assert (await execute(env, prepare(env, ids))).status == "denied"
    assert env.calls == []


@pytest.mark.parametrize("operation,ids", [
    ("toggle", ("light.allowed",)), ("turn_on", ("script.indirect",)),
    ("turn_on", ("scene.indirect",)), ("turn_on", ("group.indirect",)),
    ("trigger", ("automation.indirect",)), ("turn_on", ("all",)),
    ("turn_on", ()), ("turn_on", ("light.allowed",) * 2),
    ("turn_on", ["light.allowed"]), ("turn_on", ("light.allowed",) * 33),
    ("turn_on", ("light.allowed,light.denied",)),
])
async def test_no_arbitrary_services_indirect_domains_wildcards_or_duplicates(env, operation, ids):
    assert prepare(env, ids, operation) is None
    assert env.calls == []


@pytest.mark.parametrize(
    "change", ["policy", "exposure", "members", "missing", "registry", "kiosk"],
)
async def test_revocation_after_preparation_is_not_a_cached_grant(env, change):
    command = prepare(env)
    if change == "policy":
        env.api.async_check_access.return_value = SimpleNamespace(allowed=False)
        env.api.async_check_access.side_effect = None
    elif change == "exposure":
        env.exposed.clear()
    elif change == "members":
        env.hass.states.async_set("light.allowed", "off", {"entity_id": []})
    elif change == "missing":
        env.hass.states.async_remove("light.allowed")
    elif change == "registry":
        env.registry.async_remove("light.allowed")
        env.registry.async_get_or_create(
            "light", "test", "replacement", suggested_object_id="allowed",
        )
    else:
        env.guard.approved_kiosk_user_ids = frozenset()
    assert (await execute(env, command)).status == "denied"
    assert env.calls == []


async def test_revocation_after_preflight_before_native_task_runs_executes_nothing(env):
    env.api.async_check_access.side_effect = [SimpleNamespace(allowed=True),
                                               SimpleNamespace(allowed=False)]
    assert (await execute(env, prepare(env))).status == "denied"
    assert env.calls == []


async def test_policy_change_across_account_await_rechecks_exposure_and_caller(env):
    async def check(*args, **kwargs):
        await asyncio.sleep(0)
        env.exposed.clear()
        return SimpleNamespace(allowed=True)

    env.api.async_check_access.side_effect = check
    assert (await execute(env, prepare(env))).status == "denied"
    assert env.calls == []


async def test_concurrent_replay_consumed_before_first_await(env):
    started, release = asyncio.Event(), asyncio.Event()

    async def check(*args, **kwargs):
        started.set()
        await release.wait()
        return SimpleNamespace(allowed=True)

    env.api.async_check_access.side_effect = check
    command = prepare(env)
    first = asyncio.create_task(execute(env, command))
    await started.wait()
    assert (await execute(env, command)).status == "denied"
    assert prepare(env) is None  # A new proposal cannot replay the same turn either.
    release.set()
    assert (await first).completed == 1
    assert len(env.calls) == 1


async def test_concurrent_turns_do_not_share_subject_or_caller(env):
    other_context, other_turn = Context(user_id="second-kiosk"), turn("second-child")
    env.guard.approved_kiosk_user_ids = frozenset({"kiosk", "second-kiosk"})
    other = prepare(env, ("fan.allowed",), context=other_context, turn=other_turn)
    first, second = await asyncio.gather(
        execute(env, prepare(env)), execute(env, other, context=other_context, turn=other_turn),
    )
    assert first.completed == second.completed == 1
    assert {call[3].user_id for call in env.calls} == {"kiosk", "second-kiosk"}
    assert {(call.args[1], call.kwargs["ceiling_user_id"])
            for call in env.api.async_check_access.call_args_list} == {
        ("child", "kiosk"), ("second-child", "second-kiosk"),
    }


@pytest.mark.parametrize("mismatch", ["turn", "context", "copy", "operation"])
async def test_exact_object_binding_and_command_tampering(env, mismatch):
    command = prepare(env)
    kwargs = {}
    if mismatch == "turn":
        kwargs["turn"] = turn()
    elif mismatch == "context":
        kwargs["context"] = Context(user_id="kiosk")
    elif mismatch == "copy":
        command = replace(command)
    else:
        command = replace(command, operation="turn_off")
    assert (await execute(env, command, **kwargs)).status == "denied"
    assert env.calls == []


async def test_revocation_between_targets_stops_remainder_without_claiming_rollback(env):
    env.api.async_check_access.side_effect = [SimpleNamespace(allowed=True),
                                               SimpleNamespace(allowed=True),
                                               SimpleNamespace(allowed=False)]
    result = await execute(env, prepare(env, ("light.allowed", "fan.allowed")))
    assert result.status == "partial" and result.completed == 1
    assert len(env.calls) == 1 and env.calls[0][0] == "light"


async def test_native_handler_waits_no_detached_timeout_and_cancellation_propagates(
    env, monkeypatch,
):
    monkeypatch.setattr(rbac_execution._AwaitedHandler, "service_timeout", 0)
    started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def slow(call):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        env.calls.append(call)

    env.hass.services.async_register("light", "turn_on", slow)
    command = prepare(env)
    task = asyncio.create_task(execute(env, command))
    await started.wait()
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set() and env.calls == []
    assert (await execute(env, command)).status == "denied"


async def test_service_error_is_unconfirmed_and_never_retried(env):
    attempted = []

    async def broken(call):
        attempted.append(call)
        raise RuntimeError("PRIVATE DEVICE FAILURE")

    env.hass.services.async_register("light", "turn_on", broken)
    command = prepare(env)
    result = await execute(env, command)
    assert result.status == "unconfirmed" and result.completed == 0
    assert "PRIVATE" not in repr(result)
    assert (await execute(env, command)).status == "denied"
    assert len(attempted) == 1


async def test_mutated_caller_during_permission_await_is_denied(env):
    async def check(*args, **kwargs):
        await asyncio.sleep(0)
        env.context.user_id = "other-account"
        return SimpleNamespace(allowed=True)

    env.api.async_check_access.side_effect = check
    assert (await execute(env, prepare(env))).status == "denied"
    assert env.calls == []


async def test_ledger_capacity_fails_closed_without_evicting_replay_protection(env, monkeypatch):
    monkeypatch.setattr(rbac_execution, "MAX_COMMANDS", 1)
    first = prepare(env)
    assert first is not None
    assert prepare(env, turn=turn("second-child")) is None
    assert (await execute(env, first)).completed == 1
    assert prepare(env) is None
    assert prepare(env, turn=turn("second-child")) is None


async def test_native_adapter_refuses_broadened_arguments(env, monkeypatch):
    async def broaden(handler, domain, service, intent_obj, state):
        await intent_obj.hass.services.async_call(
            domain, service, {"entity_id": ["light.allowed", "light.denied"]},
            context=intent_obj.context, blocking=True,
        )

    monkeypatch.setattr(rbac_execution._AwaitedHandler, "async_call_service", broaden)
    assert (await execute(env, prepare(env))).status == "denied"
    assert env.calls == []


async def test_native_adapter_cannot_report_success_without_admission(env, monkeypatch):
    monkeypatch.setattr(rbac_execution._AwaitedHandler, "async_call_service", AsyncMock())
    assert (await execute(env, prepare(env))).status == "denied"
    assert env.calls == []


@pytest.mark.parametrize("failure", ["provider", "version", "expiry", "close"])
async def test_unavailable_provider_expired_or_closed_guard_never_falls_back(
    env, monkeypatch, failure,
):
    command = prepare(env)
    if failure == "provider":
        env.api.async_check_access.side_effect = RuntimeError("PRIVATE ERROR")
    elif failure == "version":
        env.api.API_VERSION = True
    elif failure == "expiry":
        monkeypatch.setattr(rbac_execution.time, "monotonic", lambda: command._expires + 1)
    else:
        env.guard.close()
    assert (await execute(env, command)).status == "denied"
    assert env.calls == []


@pytest.mark.parametrize("platform", ["group", "template"])
async def test_registry_indirect_entities_denied_even_without_member_attribute(env, platform):
    entry = env.registry.async_get_or_create("light", platform, "indirect")
    env.hass.states.async_set(entry.entity_id, "off", {})
    assert prepare(env, (entry.entity_id,)) is None


async def test_unknown_speaker_and_unapproved_account_have_no_command(env):
    assert prepare(env, turn=replace(env.prepared, verified=False)) is None
    assert prepare(env, turn=replace(env.prepared, ha_user_id=None)) is None
    assert prepare(env, context=Context(user_id="owner")) is None
