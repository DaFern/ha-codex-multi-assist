"""Bound conversation history to the HA account and its current privilege class."""

from collections import OrderedDict
from copy import copy
from dataclasses import is_dataclass, replace

DATA_HISTORY = "codex_assist_mcp_history"


async def history_input(hass, entry, user_input):
    """Start fresh for unknown ownership, changed users or changed admin status.

    Once MCP is used, keep enforcing ownership across this integration's agents,
    including after disabling MCP. HA owns the chat logs; never edit their internals.
    Eviction loses continuity, never isolation. HA restarts also lose native histories.
    """
    if not entry.options.get("mcp_servers") and DATA_HISTORY not in hass.data:
        return user_input, None
    owners = hass.data.setdefault(DATA_HISTORY, OrderedDict())
    context = user_input.context
    user = (await hass.auth.async_get_user(context.user_id)
            if context and context.user_id else None)
    actor = (user.id, bool(user.is_admin)) if (
        user and user.is_active and not user.system_generated
    ) else (None, False)
    conversation_id = user_input.conversation_id
    if conversation_id and owners.get(conversation_id) != actor:
        if is_dataclass(user_input):
            user_input = replace(user_input, conversation_id=None)
        else:
            user_input = copy(user_input)
            user_input.conversation_id = None
    return user_input, actor


def remember_history(hass, result, actor):
    if actor is None or not result.conversation_id:
        return
    owners = hass.data[DATA_HISTORY]
    owners[result.conversation_id] = actor
    owners.move_to_end(result.conversation_id)
    while len(owners) > 512:
        owners.popitem(last=False)
