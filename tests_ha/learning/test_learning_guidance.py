"""Native wizard/readiness/repair contracts, with no real pairing or microphone."""

from copy import deepcopy
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest
import test_learning_setup as setup_fixtures
import test_phone_learning_pipeline as phone_fixtures
from cryptography.fernet import Fernet
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir

from custom_components.codex_assist import DOMAIN
from custom_components.codex_assist.learning.health_issues import (
    apply_report,
    issue_id,
    observe,
)
from custom_components.codex_assist.learning.learning_bridge_protocol import BridgeError
from custom_components.codex_assist.learning.readiness import async_check_setup, technical_report

phone = phone_fixtures.phone
pipeline_components = phone_fixtures.pipeline_components


async def options_step(hass, entry, step):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


def get_issue(hass, entry, kind):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id(entry.entry_id, kind))


async def test_discovery_selection_never_pairs_until_separate_key_submission(hass):
    bridge = AsyncMock(return_value={"ready": True})
    with (
        patch(
            "custom_components.codex_assist.learning.discovery.suggested_origins",
            return_value=["http://suggested-addon:8099"],
        ),
        patch("custom_components.codex_assist.learning.bridge_client.BridgeClient.call", bridge),
    ):
        result = await setup_fixtures.begin_pairing(hass)
        assert result["step_id"] == "learning_discovery"
        bridge.assert_not_awaited()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"origin": "http://suggested-addon:8099"}
        )
        assert result["step_id"] == "voice_learning"
        bridge.assert_not_awaited()
        key_field = next(k for k in result["data_schema"].schema if k.schema == "key")
        import probatio

        assert key_field.default is probatio.UNDEFINED
        key = Fernet.generate_key().decode()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"url": "http://suggested-addon:8099", "key": key}
        )
        assert result["step_id"] == "learning_phone"
        bridge.assert_awaited_once_with("hello", None, {})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"phone_enabled": False}
        )
        assert result["step_id"] == "learning_finish"
        assert key not in str(result)
        assert not hass.config_entries.async_entries(DOMAIN)


async def test_discovery_manual_fallback_leaves_origin_unfilled(hass):
    with patch(
        "custom_components.codex_assist.learning.discovery.suggested_origins",
        return_value=["http://suggested-addon:8099"],
    ):
        result = await setup_fixtures.begin_pairing(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"origin": "manual"}
        )
    assert result["step_id"] == "voice_learning"
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_check_setup_only_sends_hello_and_cannot_pause_or_grant_consent(hass, phone):
    for marker in (1, 2):
        await phone["run"](marker)
    before = len(phone["backend"].calls)
    options = deepcopy(dict(phone["entry"].options))
    result = await options_step(hass, phone["entry"], "learning_status")
    assert result["step_id"] == "learning_status"
    assert "PRIVATE" not in str(result)
    assert phone["entry"].data["key"] not in str(result)
    assert [call[0] for call in phone["backend"].calls[before:]] == ["hello"]
    assert phone["backend"].active and phone["backend"].count == 0
    assert phone["entry"].options == options
    assert technical_report(hass, phone["entry"])["pipeline"] == "ready"
    assert technical_report(hass, phone["entry"])["launcher"] == "ready"
    assert get_issue(hass, phone["entry"], "pipeline") is None


@pytest.mark.parametrize("problem", ["missing", "ambiguous", "mismatch"])
async def test_pipeline_readiness_reports_problem_without_changing_pipelines(hass, phone, problem):
    from homeassistant.components import assist_pipeline

    existing = list(assist_pipeline.async_get_pipelines(hass))
    matching = next(p for p in existing if p.stt_engine == phone["engine"].entity_id)
    choices = {
        "missing": [],
        "ambiguous": [matching, replace(matching, id="duplicate")],
        "mismatch": [replace(matching, conversation_engine="conversation.home_assistant")],
    }
    with patch(
        "homeassistant.components.assist_pipeline.async_get_pipelines",
        return_value=choices[problem],
    ):
        report = await async_check_setup(hass, phone["entry"])
    assert report["pipeline"] == problem
    assert get_issue(hass, phone["entry"], "pipeline") is not None
    assert list(assist_pipeline.async_get_pipelines(hass)) == existing


async def test_launcher_conflict_is_reported_without_overwrite(hass, phone):
    from homeassistant.components import frontend

    from custom_components.codex_assist.learning.launcher import register_panel

    frontend.async_remove_panel(hass, "voice-match-learning")
    frontend.async_register_built_in_panel(hass, "map", frontend_url_path="voice-match-learning")
    panel = hass.data[frontend.DATA_PANELS]["voice-match-learning"]
    await register_panel(hass)
    assert (await async_check_setup(hass, phone["entry"]))["launcher"] == "conflict"
    assert hass.data[frontend.DATA_PANELS]["voice-match-learning"] is panel
    assert get_issue(hass, phone["entry"], "launcher") is not None


@pytest.mark.parametrize("setting", ["embed_iframe", "require_admin"])
async def test_incompatible_launcher_settings_are_not_reported_ready(hass, phone, setting):
    from homeassistant.components import frontend, panel_custom

    from custom_components.codex_assist.learning.const import MODULE_URL, PANEL_PATH
    from custom_components.codex_assist.learning.launcher import register_panel

    frontend.async_remove_panel(hass, PANEL_PATH)
    settings = {"embed_iframe": False, "require_admin": False, setting: True}
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name="voice-match-launch-panel",
        module_url=MODULE_URL,
        **settings,
    )
    before = hass.data[frontend.DATA_PANELS][PANEL_PATH]
    await register_panel(hass)
    assert (await async_check_setup(hass, phone["entry"]))["launcher"] == "conflict"
    assert hass.data[frontend.DATA_PANELS][PANEL_PATH] is before


async def test_bridge_failure_never_exposes_peer_data_or_clears_another_entry(hass, phone):
    entry = phone["entry"]
    other = setup_fixtures.learning_entry()
    other.add_to_hass(hass)
    observe(hass, other, "bridge", "unavailable")
    with patch(
        "custom_components.codex_assist.learning.bridge_client.BridgeClient.call",
        AsyncMock(side_effect=BridgeError("PRIVATE")),
    ):
        report = await async_check_setup(hass, entry)
    assert report["bridge"] == "unavailable" and "PRIVATE" not in str(report)
    issue = get_issue(hass, entry, "bridge")
    assert issue.data == {"entry_id": entry.entry_id, "kind": "bridge"}
    assert entry.data["key"] not in repr(issue)
    await async_check_setup(hass, entry)
    assert get_issue(hass, entry, "bridge") is None
    assert get_issue(hass, other, "bridge") is not None


async def test_changed_configuration_during_check_keeps_prior_issues(hass, phone):
    entry = phone["entry"]
    observe(hass, entry, "bridge", "unavailable")
    saved = dict(entry.data)

    async def hello(*args):
        hass.config_entries.async_update_entry(
            entry, data={**saved, "key": Fernet.generate_key().decode()}
        )
        return {"ready": True}

    with (
        patch("custom_components.codex_assist.learning.bridge_client.BridgeClient.call", hello),
        patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)),
    ):
        report = await async_check_setup(hass, entry)
        await hass.async_block_till_done()
        assert set(report.values()) == {"not_checked"}
        assert get_issue(hass, entry, "bridge") is not None
        hass.config_entries.async_update_entry(entry, data=saved)
        await hass.async_block_till_done()


async def test_unknown_evidence_and_reload_preserve_dismissal_but_removal_cleans_own_issues(
    hass, phone
):
    entry = phone["entry"]
    observe(hass, entry, "pipeline", "missing")
    ir.async_ignore_issue(hass, DOMAIN, issue_id(entry.entry_id, "pipeline"), True)
    issue = get_issue(hass, entry, "pipeline")
    apply_report(
        hass,
        entry,
        dict.fromkeys(("bridge", "source", "entities", "pipeline", "launcher"), "not_checked"),
    )
    assert get_issue(hass, entry, "pipeline") is issue and issue.dismissed_version is not None
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    # Matching pipeline after reload is observed evidence, so issue may resolve;
    # unrelated/unknown evidence must not delete and recreate an ignored issue.
    observe(hass, entry, "pipeline", "missing")
    other = setup_fixtures.learning_entry()
    other.add_to_hass(hass)
    observe(hass, other, "pipeline", "missing")
    await hass.config_entries.async_remove(other.entry_id)
    assert get_issue(hass, other, "pipeline") is None
    assert get_issue(hass, entry, "pipeline") is not None


async def make_repair(hass, entry, kind):
    from custom_components.codex_assist.repairs import async_create_fix_flow

    key = issue_id(entry.entry_id, kind)
    data = {"entry_id": entry.entry_id, "kind": kind}
    flow = await async_create_fix_flow(hass, key, data)
    flow.hass, flow.data = hass, data
    flow.context = {"issue_id": key}
    return flow


async def test_bridge_repair_only_opens_bound_reconfigure_after_confirmation(hass, phone):
    entry = phone["entry"]
    observe(hass, entry, "bridge", "unavailable")
    flow = await make_repair(hass, entry, "bridge")
    before = list(phone["backend"].calls)
    assert (await flow.async_step_init())["step_id"] == "confirm"
    assert phone["backend"].calls == before
    result = await flow.async_step_confirm({})
    assert result["type"] is FlowResultType.ABORT
    next_flow = hass.config_entries.flow.async_get(result["next_flow"][1])
    assert next_flow["context"]["entry_id"] == entry.entry_id
    assert next_flow["step_id"] == "voice_learning"
    assert phone["backend"].calls == before
    assert get_issue(hass, entry, "bridge") is not None


async def test_pipeline_repair_does_not_clear_unresolved_issue(hass, phone):
    observe(hass, phone["entry"], "pipeline", "missing")
    flow = await make_repair(hass, phone["entry"], "pipeline")
    assert (await flow.async_step_confirm({}))["step_id"] == "check"
    with patch("homeassistant.components.assist_pipeline.async_get_pipelines", return_value=[]):
        result = await flow.async_step_check({})
    assert result["errors"] == {"base": "not_resolved"}
    assert get_issue(hass, phone["entry"], "pipeline") is not None
    assert (await flow.async_step_check({}))["type"] is FlowResultType.CREATE_ENTRY
    assert get_issue(hass, phone["entry"], "pipeline") is None


async def test_repair_rejects_codex_or_spoofed_issue_scope(hass, phone):
    codex = await setup_fixtures.setup_codex(hass)
    flow = await make_repair(hass, codex, "bridge")
    assert (await flow.async_step_init())["reason"] == "learning_entry_unavailable"
    flow = await make_repair(hass, phone["entry"], "bridge")
    flow.context = {"issue_id": issue_id(codex.entry_id, "bridge")}
    assert (await flow.async_step_init())["reason"] == "learning_entry_unavailable"


@pytest.mark.parametrize("problem", ["disabled", "removed"])
async def test_repair_rejects_disabled_or_removed_entry_without_network(hass, problem):
    from homeassistant.config_entries import ConfigEntryDisabler

    entry = setup_fixtures.learning_entry(
        disabled_by=ConfigEntryDisabler.USER if problem == "disabled" else None
    )
    entry.add_to_hass(hass)
    flow = await make_repair(hass, entry, "bridge")
    if problem == "removed":
        await hass.config_entries.async_remove(entry.entry_id)
    with patch(
        "custom_components.codex_assist.learning.bridge_client.BridgeClient.call",
        side_effect=AssertionError("Invalid repair must not contact a bridge"),
    ):
        assert (await flow.async_step_init())["reason"] == "learning_entry_unavailable"


async def test_personalisation_guidance_selects_explicit_target_without_copying_keys(hass, phone):
    codex = await setup_fixtures.setup_codex(hass)
    key = Fernet.generate_key().decode()
    hass.config_entries.async_update_entry(codex, options={"voice_match_pairing_key": key})
    await hass.async_block_till_done()
    before = dict(codex.options)
    result = await options_step(hass, phone["entry"], "learning_personalisation")
    assert result["step_id"] == "learning_personalisation"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entry_id": codex.entry_id}
    )
    assert result["step_id"] == "learning_personalisation_guide"
    assert "not verified" in result["description_placeholders"]["pairing_status"]
    assert key not in str(result) and phone["entry"].data["key"] not in str(result)
    assert codex.options == before
    assert "voice_match_pairing_key" not in phone["entry"].data


async def test_personalisation_is_optional_without_codex_or_oauth(hass, phone):
    with patch(
        "custom_components.codex_assist.config_flow.CodexAssistConfigFlow._auth_client",
        side_effect=AssertionError("No cloud setup from learning guidance"),
    ):
        result = await options_step(hass, phone["entry"], "learning_personalisation")
    assert result["step_id"] == "learning_personalisation_missing"


async def test_source_repair_opens_only_learning_options(hass, phone):
    observe(hass, phone["entry"], "source", "unavailable")
    flow = await make_repair(hass, phone["entry"], "source")
    result = await flow.async_step_confirm({})
    assert result["next_flow"][0] == "options_flow"
    next_flow = hass.config_entries.options.async_get(result["next_flow"][1])
    assert next_flow["handler"] == phone["entry"].entry_id
    assert next_flow["step_id"] == "learning_menu"
    assert get_issue(hass, phone["entry"], "source") is not None


async def test_real_repair_manager_requires_verified_recheck_before_clearing(hass, phone):
    from homeassistant.components.repairs import repairs_flow_manager

    entry = phone["entry"]
    observe(hass, entry, "pipeline", "missing")
    manager = repairs_flow_manager(hass)
    result = await manager.async_init(
        DOMAIN, context={"issue_id": issue_id(entry.entry_id, "pipeline")}
    )
    assert result["step_id"] == "confirm"
    result = await manager.async_configure(result["flow_id"], {})
    assert result["step_id"] == "check"
    with patch("homeassistant.components.assist_pipeline.async_get_pipelines", return_value=[]):
        result = await manager.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "not_resolved"}
    assert get_issue(hass, entry, "pipeline") is not None
    result = await manager.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert get_issue(hass, entry, "pipeline") is None


async def test_missing_source_repair_is_created_and_only_cleared_after_availability(hass, phone):
    source_id = phone["source"].entity_id
    state = hass.states.get(source_id)
    hass.states.async_set(source_id, "unavailable")
    report = await async_check_setup(hass, phone["entry"])
    assert report["source"] == "unavailable"
    assert get_issue(hass, phone["entry"], "source") is not None
    hass.states.async_set(source_id, state.state, state.attributes)
    assert (await async_check_setup(hass, phone["entry"]))["source"] == "available"
    assert get_issue(hass, phone["entry"], "source") is None


async def test_ignored_observed_problem_stays_ignored_through_reload(hass, phone):
    entry = phone["entry"]
    with patch("homeassistant.components.assist_pipeline.async_get_pipelines", return_value=[]):
        await async_check_setup(hass, entry)
        ir.async_ignore_issue(hass, DOMAIN, issue_id(entry.entry_id, "pipeline"), True)
        before = get_issue(hass, entry, "pipeline")
        assert before.dismissed_version is not None
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        await async_check_setup(hass, entry)
        after = get_issue(hass, entry, "pipeline")
        assert (
            after.created == before.created and after.dismissed_version == before.dismissed_version
        )


async def test_failed_unload_is_not_presented_as_disabled_success(hass):
    entry = setup_fixtures.learning_entry(options={"phone_enabled": False})
    entry.add_to_hass(hass)
    with patch(
        "custom_components.codex_assist.learning.bridge_client.BridgeClient.call",
        AsyncMock(return_value={"ready": True}),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
    entry.runtime_data.coordinator._state["restored"] = False
    assert not await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.FAILED_UNLOAD
    report = technical_report(hass, entry)
    assert report["entities"] == "not_loaded"
    assert report["pipeline"] == "not_checked"
