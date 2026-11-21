"""Shared durable context with deterministic storage and no saved authority."""

import copy
from unittest.mock import AsyncMock

import pytest

from custom_components.codex_assist.protected_history import (
    MAX_HISTORY_CHARS,
    MAX_MESSAGES,
    SharedSatelliteHistory,
)

EID = "assist_satellite.test"
BINDING = "a" * 64
CHANNEL = "b" * 64
CHILD = "c" * 64
OWNER = "d" * 64
PUBLIC = "e" * 64
PRIVATE = "f" * 64
MESSAGES = [{"role": "user", "content": "Which song?"},
            {"role": "assistant", "content": "Would you like this version?"}]
CHOICES = {"song": ["media_player.test", {"uri": "library://track/1", "name": "Test"}]}


@pytest.fixture
def journal(hass):
    history = SharedSatelliteHistory(hass, "test-entry", [EID])
    saved = {}

    async def load():
        return copy.deepcopy(saved.get("data"))

    async def save(data):
        saved["data"] = copy.deepcopy(data)

    history._store.async_load = AsyncMock(side_effect=load)
    history._store.async_save = AsyncMock(side_effect=save)
    return history, saved


async def append(history, view=None, speaker=OWNER, messages=None, choices=None):
    await history.async_load()
    return await history.async_append(
        EID, BINDING, CHANNEL, speaker, [PUBLIC] if view is None else view,
        MESSAGES if messages is None else messages, CHOICES if choices is None else choices,
    )


async def test_restart_restores_plain_shared_dialogue_but_not_microphone_or_authority(
    hass, journal,
):
    history, saved = journal
    await append(history)
    replacement = SharedSatelliteHistory(hass, "test-entry", [EID])
    replacement._store.async_load = AsyncMock(return_value=saved["data"])
    await replacement.async_load()
    rows, choices = replacement.previous(EID, BINDING, CHANNEL, [PUBLIC])
    assert rows[0]["content"] == f"Participant {OWNER[:12]}: Which song?"
    assert choices == CHOICES
    assert not hasattr(replacement, "timer") and not hasattr(replacement, "context")
    assert "authorization" not in repr(saved)


async def test_less_privileged_participant_cannot_receive_any_part_of_a_private_turn(journal):
    history, _saved = journal
    await append(history, [PUBLIC, PRIVATE])
    assert history.previous(EID, BINDING, CHANNEL, [PUBLIC]) == ([], {})
    # A public turn by a different participant is shared without erasing private turns.
    await append(history, speaker=CHILD, choices={})
    rows, _choices = history.previous(EID, BINDING, CHANNEL, [PUBLIC])
    assert len(rows) == 2 and CHILD[:12] in rows[0]["content"]
    rows, _choices = history.previous(EID, BINDING, CHANNEL, [PUBLIC, PRIVATE])
    assert len(rows) == 4 and OWNER[:12] in rows[0]["content"]


async def test_changed_registry_field_projection_or_channel_hides_history_without_erasing(journal):
    history, _saved = journal
    await append(history)
    assert history.previous(EID, BINDING, CHANNEL, [PRIVATE]) == ([], {})
    assert history.previous(EID, PRIVATE, CHANNEL, [PUBLIC]) == ([], {})
    assert history.previous(EID, BINDING, PRIVATE, [PUBLIC]) == ([], {})
    assert history.previous("assist_satellite.other", BINDING, CHANNEL, [PUBLIC]) == ([], {})
    assert history.previous(EID, BINDING, CHANNEL, [PUBLIC])[0]


async def test_successful_choice_consumption_is_durable_before_effect(journal):
    history, saved = journal
    await append(history)
    await history.async_consume_choices(EID, BINDING)
    assert saved["data"]["satellites"][EID]["choices"] == {}
    rows, choices = history.previous(EID, BINDING, CHANNEL, [PUBLIC])
    assert rows and choices == {}


async def test_save_failure_cannot_publish_new_dialogue_or_claim_choice_consumed(journal):
    history, saved = journal
    await append(history)
    before = copy.deepcopy(saved)
    history._store.async_save.side_effect = OSError("Synthetic disk failure")
    with pytest.raises(OSError):
        await history.async_consume_choices(EID, BINDING)
    assert saved == before
    assert history.previous(EID, BINDING, CHANNEL, [PUBLIC])[1] == CHOICES
    with pytest.raises(OSError):
        await append(history, speaker=CHILD)
    assert len(history.previous(EID, BINDING, CHANNEL, [PUBLIC])[0]) == 2


async def test_silent_store_write_failure_does_not_count_as_durable_consumption(journal):
    history, _saved = journal
    await append(history)
    history._store.async_save.side_effect = None
    with pytest.raises(RuntimeError, match="not verified"):
        await history.async_consume_choices(EID, BINDING)
    assert history.previous(EID, BINDING, CHANNEL, [PUBLIC])[1] == CHOICES


async def test_forget_only_deletes_currently_permitted_context(journal):
    history, _saved = journal
    await append(history, [PUBLIC, PRIVATE])
    await append(history, speaker=CHILD)
    await history.async_forget(EID, BINDING, CHANNEL, [PUBLIC])
    assert history.previous(EID, BINDING, CHANNEL, [PUBLIC]) == ([], {})
    rows, _ = history.previous(EID, BINDING, CHANNEL, [PUBLIC, PRIVATE])
    assert len(rows) == 2 and OWNER[:12] in rows[0]["content"]


async def test_private_store_is_bounded_and_does_not_retain_executable_objects(journal):
    import json

    history, saved = journal

    class Transcript(str):
        authority = object()

    for _ in range(30):
        await append(
            history,
            messages=[{"role": "user", "content": Transcript("x" * 2000)},
                      {"role": "assistant", "content": "y" * 2000}],
            choices={"song": ["media_player.test", {"uri": "library://track/1",
                                                   "authority": object()}]},
        )
    data = saved["data"]["satellites"][EID]
    rows = [message for turn in data["turns"] for message in turn["messages"]]
    assert len(rows) <= MAX_MESSAGES and len(json.dumps(rows)) <= MAX_HISTORY_CHARS
    assert all(type(row["content"]) is str for row in rows)
    assert data["choices"]["items"]["song"][1] == {"uri": "library://track/1"}
    assert history._store._private and history._store._atomic_writes


@pytest.mark.parametrize("value", [None, 3, {}, object()])
async def test_invalid_history_is_not_iterated_or_saved(journal, value):
    history, saved = journal
    await history.async_load()
    assert not await history.async_append(
        EID, BINDING, CHANNEL, OWNER, [PUBLIC], value, {},
    )
    assert not saved


async def test_loaded_memory_is_validated_and_restricted_to_current_enrollment(journal):
    history, saved = journal
    await append(history)
    history._loaded = False
    saved["data"]["satellites"]["assist_satellite.other"] = copy.deepcopy(
        saved["data"]["satellites"][EID],
    )
    saved["data"]["satellites"][EID]["turns"].append({"messages": object()})
    await history.async_load()
    assert list(history._satellites) == [EID]
    assert len(history.previous(EID, BINDING, CHANNEL, [PUBLIC])[0]) == 2
