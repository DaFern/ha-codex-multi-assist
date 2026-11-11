"""Account-scoped native histories fail closed when ownership is lost."""

from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.core import Context

from custom_components.codex_assist.mcp_history import (
    DATA_HISTORY,
    history_input,
    remember_history,
)


async def test_owner_change_demotion_disabled_mcp_and_eviction(hass, hass_admin_user, monkeypatch):
    entry = SimpleNamespace(options={"mcp_servers": [{"enabled": True}]})
    message = SimpleNamespace(context=Context(user_id=hass_admin_user.id), conversation_id="old")
    fresh, actor = await history_input(hass, entry, message)
    assert fresh.conversation_id is None
    assert message.conversation_id == "old"
    remember_history(hass, SimpleNamespace(conversation_id="old"), actor)
    retained, _ = await history_input(hass, entry, message)
    assert retained is message
    # Even disabling MCP must not make its old history available to a new actor.
    entry.options = {}
    user = SimpleNamespace(id=hass_admin_user.id, is_active=True,
                           is_admin=False, system_generated=False)
    monkeypatch.setattr(hass.auth, "async_get_user", AsyncMock(return_value=user))
    assert (await history_input(hass, entry, message))[0].conversation_id is None
    monkeypatch.setattr(hass.auth, "async_get_user", AsyncMock(return_value=None))
    assert (await history_input(hass, entry, message))[0].conversation_id is None
    hass.data[DATA_HISTORY] = OrderedDict()
    for index in range(513):
        remember_history(hass, SimpleNamespace(conversation_id=str(index)), actor)
    assert len(hass.data[DATA_HISTORY]) == 512
    assert "0" not in hass.data[DATA_HISTORY]
