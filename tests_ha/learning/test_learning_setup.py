"""Separate pairing, opt-in, repair, outages and shutdown alongside real Codex."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import test_phone_learning_pipeline as phone_fixtures
from cryptography.fernet import Fernet
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist import DOMAIN, async_unload_entry
from custom_components.codex_assist.codex_auth import (
    CodexAuthorizationCode,
    CodexDeviceCode,
    CodexTokenSet,
)
from custom_components.codex_assist.codex_runtime import runtime_token_coordinator
from custom_components.codex_assist.learning.learning_bridge_protocol import BridgeError

phone = phone_fixtures.phone
phone_probe = phone_fixtures.phone_probe
speech = phone_fixtures.speech


def learning_entry(**kwargs):
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN + ":voice_match",
        title="Voice Match learning",
        data={
            "module": "voice_match",
            "url": "http://addon:8099",
            "key": Fernet.generate_key().decode(),
        },
        **kwargs,
    )


async def setup_codex(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="Codex Assist",
        data={
            "module": "codex",
            "access_token": "test-access",
            "refresh_token": "test-refresh",
            "model": "gpt-5.4",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def begin_pairing(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "voice_learning"}
    )


@pytest.mark.parametrize("with_codex", [False, True])
async def test_pairing_and_phone_opt_in_need_no_codex_account(hass, monkeypatch, with_codex):
    codex = await setup_codex(hass) if with_codex else None
    codex_runtime = codex.runtime_data if codex else None
    auth = Mock(side_effect=AssertionError("Learning must not start Codex OAuth"))
    monkeypatch.setattr(
        "custom_components.codex_assist.config_flow.CodexAssistConfigFlow._auth_client", auth
    )
    bridge = AsyncMock(return_value={"ready": True})
    key = Fernet.generate_key().decode()
    with patch("custom_components.codex_assist.learning.bridge_client.BridgeClient.call", bridge):
        result = await begin_pairing(hass)
        assert result["step_id"] == "voice_learning"
        field, password = next(
            (k, v) for k, v in result["data_schema"].schema.items() if k.schema == "key"
        )
        assert password.config["type"] == "password"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"url": "http://addon:8099/", "key": key}
        )
        assert result["step_id"] == "learning_phone"
        assert key not in str(result)
        enabled = next(k for k in result["data_schema"].schema if k.schema == "phone_enabled")
        assert enabled.default() is False
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"phone_enabled": False}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data == {"module": "voice_match", "url": "http://addon:8099", "key": key}
    assert entry.runtime_data.phone is None and entry.runtime_data.platforms == ()
    if codex is None:
        assert not hass.states.async_entity_ids("ai_task")
    else:
        assert codex.runtime_data is codex_runtime and codex.state is ConfigEntryState.LOADED
    assert not hass.states.async_entity_ids("stt")
    assert "access_token" not in entry.data and "refresh_token" not in entry.data
    assert all(call.args == ("hello", None, {}) for call in bridge.await_args_list)
    auth.assert_not_called()


@pytest.mark.parametrize("problem", ["key", "url", "handshake"])
async def test_failed_pairing_saves_nothing_and_never_echoes_credentials(hass, problem):
    result = await begin_pairing(hass)
    key = Fernet.generate_key().decode() if problem != "key" else "synthetic-invalid-key"
    url = "http://addon:8099/forbidden" if problem == "url" else "http://addon:8099"
    bridge = AsyncMock(side_effect=BridgeError("synthetic-peer-secret"))
    with patch("custom_components.codex_assist.learning.bridge_client.BridgeClient.call", bridge):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"url": url, "key": key}
        )
    assert result["errors"] == {"base": "cannot_connect"}
    assert key not in str(result) and "synthetic-peer-secret" not in str(result)
    assert not hass.config_entries.async_entries(DOMAIN)
    if problem != "handshake":
        bridge.assert_not_awaited()


async def test_learning_reconfigure_keeps_blank_key_and_only_reloads_learning(hass, monkeypatch):
    codex = await setup_codex(hass)
    learning = learning_entry(options={"phone_enabled": False})
    saved_key = learning.data["key"]
    learning.add_to_hass(hass)
    reload_entry = AsyncMock(return_value=True)
    monkeypatch.setattr(hass.config_entries, "async_reload", reload_entry)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": learning.entry_id}
    )
    assert learning.data["key"] not in str(result)
    with patch(
        "custom_components.codex_assist.learning.bridge_client.BridgeClient.call",
        AsyncMock(return_value={"ready": True}),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"url": "http://replacement-addon:8099/", "key": ""}
        )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert learning.data["url"] == "http://replacement-addon:8099"
    assert learning.data["key"] == saved_key
    assert learning.options == {"phone_enabled": False}
    reload_entry.assert_awaited_once_with(learning.entry_id)
    assert codex.state is ConfigEntryState.LOADED


async def test_learning_outage_retry_and_recovery_do_not_reload_codex(hass, caplog):
    codex = await setup_codex(hass)
    lock = runtime_token_coordinator(codex)
    runtime = codex.runtime_data
    learning = learning_entry()
    learning.add_to_hass(hass)
    with patch(
        "custom_components.codex_assist.learning.bridge_client.BridgeClient.call",
        AsyncMock(side_effect=BridgeError("synthetic-peer-secret")),
    ):
        assert not await hass.config_entries.async_setup(learning.entry_id)
        await hass.async_block_till_done()
    assert learning.state is ConfigEntryState.SETUP_RETRY
    assert codex.state is ConfigEntryState.LOADED and codex.runtime_data is runtime
    assert "synthetic-peer-secret" not in caplog.text
    with patch(
        "custom_components.codex_assist.learning.bridge_client.BridgeClient.call",
        AsyncMock(return_value={"ready": True}),
    ):
        assert await hass.config_entries.async_reload(learning.entry_id)
        await hass.async_block_till_done()
    assert learning.state is ConfigEntryState.LOADED
    assert codex.runtime_data is runtime and runtime_token_coordinator(codex) is lock
    assert await hass.config_entries.async_unload(learning.entry_id)
    assert codex.state is ConfigEntryState.LOADED


async def test_learning_options_disable_pauses_without_discard_or_codex_reload(hass, phone):
    codex = await setup_codex(hass)
    runtime = codex.runtime_data
    for marker in (1, 2, 3):
        await phone["run"](marker)
    result = await hass.config_entries.options.async_init(phone["entry"].entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"phone_enabled": False}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert phone["entry"].runtime_data.phone is None
    assert phone["backend"].count == 1 and not phone["backend"].active
    assert not [call for call in phone["backend"].calls if call[0] == "discard"]
    assert codex.state is ConfigEntryState.LOADED and codex.runtime_data is runtime
    assert hass.states.get("ai_task.codex_assist_ai_task") is not None


async def test_codex_reauthentication_reload_does_not_interrupt_consented_learning(hass, phone):
    codex = await setup_codex(hass)
    await phone["run"](1)
    await phone["run"](2)
    controller = phone["runtime"].controller
    auth = SimpleNamespace(
        request_device_code=AsyncMock(
            return_value=CodexDeviceCode(
                user_code="TEST-CODE",
                device_auth_id="test-device",
                interval=5,
                verification_uri="https://auth.openai.com/codex/device",
            )
        ),
        poll_device_code=AsyncMock(return_value=CodexAuthorizationCode("test-code", "verifier")),
        exchange_authorization_code=AsyncMock(
            return_value=CodexTokenSet("new-access", "new-refresh")
        ),
    )
    with patch(
        "custom_components.codex_assist.config_flow.CodexAssistConfigFlow._auth_client",
        return_value=auth,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reauth", "entry_id": codex.entry_id}, data=codex.data
        )
        for _ in range(2):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert codex.data["access_token"] == "new-access"
    assert phone["entry"].runtime_data.phone.controller is controller
    assert not controller.closing
    assert "Sample 2 of 2" in speech(await phone["run"](3))


async def test_learning_shutdown_failure_cannot_unload_codex_or_forget_runtime(hass, phone):
    codex = await setup_codex(hass)
    learning_runtime = phone["entry"].runtime_data
    with patch.object(phone["runtime"], "shutdown", AsyncMock(return_value=False)):
        assert not await async_unload_entry(hass, phone["entry"])
    assert phone["entry"].runtime_data is learning_runtime
    assert codex.state is ConfigEntryState.LOADED
    assert "Before we begin" in speech(await phone["run"](1))


async def test_management_websocket_cannot_use_codex_entry_as_learning_runtime(hass, phone):
    codex = await setup_codex(hass)
    await phone["client"].send_json(
        {
            "id": 9001,
            "type": DOMAIN + "/voice_learning/manage",
            "entry_id": codex.entry_id,
            "action": "cancel",
        }
    )
    result = await phone["client"].receive_json()
    assert result["error"]["code"] == "not_ready"
    assert not phone["backend"].active


async def test_missing_whisper_retries_only_learning(hass):
    codex = await setup_codex(hass)
    runtime = codex.runtime_data
    learning = learning_entry(options={"phone_enabled": True, "control_stt_engine": "stt.missing"})
    learning.add_to_hass(hass)
    with patch(
        "custom_components.codex_assist.learning.bridge_client.BridgeClient.call",
        AsyncMock(return_value={"ready": True}),
    ):
        assert not await hass.config_entries.async_setup(learning.entry_id)
    assert learning.state is ConfigEntryState.SETUP_RETRY
    assert codex.state is ConfigEntryState.LOADED and codex.runtime_data is runtime


async def test_codex_unload_leaves_learning_session_and_permits_intact(hass, phone):
    codex = await setup_codex(hass)
    await phone["run"](1)
    await phone["run"](2)
    assert await hass.config_entries.async_unload(codex.entry_id)
    await hass.async_block_till_done()
    assert not phone["runtime"].controller.closing
    assert "Sample 2 of 2" in speech(await phone["run"](3))


async def test_management_rejects_spoofed_scope_and_unregistered_speaker(phone):
    before = list(phone["backend"].calls)
    for index, extra in enumerate(({"user_id": "other"}, {"consent": True}), 9100):
        await phone["client"].send_json(
            {
                "id": index,
                "type": DOMAIN + "/voice_learning/manage",
                "entry_id": phone["entry"].entry_id,
                "action": "start",
                "voice_id": "assigned-profile",
                "satellite_id": "assist_satellite.fake",
                **extra,
            }
        )
        result = await phone["client"].receive_json()
        assert not result["success"]
    assert phone["backend"].calls == before
    assert not phone["entry"].runtime_data.coordinator.running


async def test_non_admin_cannot_inspect_or_cancel_other_coordinator(hass, hass_ws_client, phone):
    phone["entry"].runtime_data.coordinator.actor_id = "another-account"
    user = await hass.auth.async_create_user("Synthetic user", group_ids=["system-users"])
    token = await hass.auth.async_create_refresh_token(user, client_id="http://synthetic-client")
    client = await hass_ws_client(hass, hass.auth.async_create_access_token(token))
    for index, action in enumerate(("status", "cancel"), 9200):
        await client.send_json(
            {
                "id": index,
                "type": DOMAIN + "/voice_learning/manage",
                "entry_id": phone["entry"].entry_id,
                "action": action,
            }
        )
        result = await client.receive_json()
        assert result["error"]["code"] == "unauthorized"
