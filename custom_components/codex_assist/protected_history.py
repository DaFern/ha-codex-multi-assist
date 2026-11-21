"""Private, bounded shared dialogue through HA storage; never saved authority."""

import asyncio
import copy
import hashlib
import json

from homeassistant.helpers.storage import Store

MAX_TURNS = 32
MAX_MESSAGES = 64
MAX_HISTORY_CHARS = 64000
MAX_VIEW = 4096


def is_digest(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def plain_messages(value):
    """Copy canonical text only, stripping transcript subclasses and private metadata."""
    if type(value) is not list:
        return []
    rows = [
        {"role": row["role"], "content": str(row["content"])}
        for row in value[:MAX_MESSAGES]
        if type(row) is dict and type(row.get("role")) is str
        and row["role"] in {"user", "assistant"}
        and isinstance(row.get("content"), str) and 0 < len(row["content"]) <= 8192
    ]
    if not rows or rows[0]["role"] != "user" or rows[-1]["role"] != "assistant":
        return []
    return rows if len(json.dumps(rows)) <= MAX_HISTORY_CHARS else []


def plain_candidates(value):
    """Keep finite music data, never arbitrary model objects, callbacks or credentials."""
    result = {}
    if type(value) is not dict:
        return result
    for token, candidate in list(value.items())[:10]:
        if (
            type(token) is not str or not 0 < len(token) <= 64
            or not isinstance(candidate, (list, tuple)) or len(candidate) != 2
            or type(candidate[0]) is not str or not candidate[0].startswith("media_player.")
            or len(candidate[0]) > 255 or type(candidate[1]) is not dict
        ):
            continue
        item = {
            key: data for key, data in candidate[1].items()
            if key in {"uri", "media_type", "name", "artist"}
            and type(data) is str and len(data) <= 2048
        }
        if item.get("uri"):
            result[token] = [candidate[0], item]
    return result


def checked_view(value):
    if type(value) is not list or not 0 < len(value) <= MAX_VIEW:
        return None
    return sorted(set(value)) if all(is_digest(row) for row in value) else None


def channel_digest(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


class SharedSatelliteHistory:
    """Entry-owned journal, filtered only after this turn's fresh verification.

    A turn is available only if its *entire* input visibility is still available.
    Free-form dialogue cannot safely be redacted by guessing entity references.
    Saved speaker labels are attribution data, never identity evidence or grants.
    """

    def __init__(self, hass, entry_id, approved_ids):
        self._store = Store(
            hass, 1, f"codex_assist.satellite_history.{entry_id}",
            private=True, atomic_writes=True,
        )
        self._hass = hass
        self._approved = frozenset(approved_ids)
        self._lock = asyncio.Lock()
        self._loaded = False
        self._satellites = {}

    def set_approved(self, approved_ids):
        """Limit future reads/writes to the entry's current explicit enrollment."""
        self._approved = frozenset(approved_ids)

    @staticmethod
    def _bound_turns(turns):
        turns = turns[-MAX_TURNS:]
        while turns and (
            sum(len(row["messages"]) for row in turns) > MAX_MESSAGES
            or len(json.dumps([row["messages"] for row in turns])) > MAX_HISTORY_CHARS
        ):
            turns.pop(0)
        return turns

    async def async_load(self):
        async with self._lock:
            if self._loaded:
                return
            data = await self._store.async_load()
            satellites = data.get("satellites", {}) if type(data) is dict else {}
            if type(satellites) is dict:
                for eid in self._approved:
                    record = satellites.get(eid)
                    if type(record) is not dict or not is_digest(record.get("binding")):
                        continue
                    turns = []
                    raw_turns = record.get("turns", [])
                    for row in raw_turns[-MAX_TURNS:] if type(raw_turns) is list else ():
                        if type(row) is not dict:
                            continue
                        view = checked_view(row.get("view"))
                        messages = plain_messages(row.get("messages"))
                        if (view and messages and is_digest(row.get("channel"))
                                and is_digest(row.get("speaker"))):
                            turns.append({
                                "channel": row["channel"], "speaker": row["speaker"],
                                "view": view, "messages": messages,
                            })
                    choices = record.get("choices")
                    cleaned_choices = {}
                    if (
                        type(choices) is dict and checked_view(choices.get("view"))
                        and is_digest(choices.get("channel"))
                    ):
                        cleaned_choices = {
                            "channel": choices["channel"], "view": checked_view(choices["view"]),
                            "items": plain_candidates(choices.get("items")),
                        }
                    self._satellites[eid] = {
                        "binding": record["binding"], "turns": self._bound_turns(turns),
                        "choices": cleaned_choices,
                    }
            self._loaded = True

    def previous(self, eid, binding, channel, view):
        """Return a freshly permitted copy; never erase another participant's turns."""
        record = self._satellites.get(eid)
        current = checked_view(view)
        if (eid not in self._approved or not self._loaded or not current
                or not record or record["binding"] != binding):
            return [], {}
        visible = set(current)
        history = []
        for turn in record["turns"]:
            if turn["channel"] == channel and set(turn["view"]) <= visible:
                for row in turn["messages"]:
                    content = row["content"]
                    if row["role"] == "user":
                        content = f"Participant {turn['speaker'][:12]}: {content}"
                    history.append({"role": row["role"], "content": content})
        choices = record["choices"]
        candidates = (
            copy.deepcopy(choices["items"])
            if choices and choices["channel"] == channel and set(choices["view"]) <= visible
            else {}
        )
        return history, candidates

    async def async_append(self, eid, binding, channel, speaker, view, messages, candidates):
        """Save only after admission's post-handler policy recheck has completed."""
        clean_view, clean_messages = checked_view(view), plain_messages(messages)
        if (
            eid not in self._approved or not all(map(is_digest, (binding, channel, speaker)))
            or not clean_view or not clean_messages
        ):
            return False
        async with self._lock:
            if not self._loaded:
                raise RuntimeError("Conversation store not loaded")
            old = self._satellites.get(eid)
            turns = copy.deepcopy(old["turns"]) if old and old["binding"] == binding else []
            turns.append({
                "channel": channel, "speaker": speaker, "view": clean_view,
                "messages": clean_messages,
            })
            record = {
                "binding": binding, "turns": self._bound_turns(turns),
                "choices": {
                    "channel": channel, "view": clean_view,
                    "items": plain_candidates(candidates),
                },
            }
            await self._async_replace(eid, record)
        return True

    async def _async_replace(self, eid, record):
        # Publish in memory only after the supported private atomic save completes.
        candidate = {
            key: value for key, value in {**self._satellites, eid: record}.items()
            if key in self._approved
        }
        if self._hass.is_stopping:
            raise RuntimeError("Cannot confirm a durable conversation write during shutdown")
        document = {"satellites": copy.deepcopy(candidate)}
        await self._store.async_save(document)
        # Store.async_save logs some write failures instead of raising, and may
        # defer writes during shutdown. A completed await alone is not durability.
        if self._hass.is_stopping or await self._store.async_load() != document:
            raise RuntimeError("Conversation save was not verified")
        self._satellites = candidate

    async def async_consume_choices(self, eid, binding):
        """Persist consumption before playback, preventing restart replay after an effect."""
        async with self._lock:
            record = self._satellites.get(eid)
            if not self._loaded:
                raise RuntimeError("Conversation store not loaded")
            if record and record["binding"] == binding and record["choices"]:
                updated = copy.deepcopy(record)
                updated["choices"] = {}
                await self._async_replace(eid, updated)

    async def async_forget(self, eid, binding, channel, view):
        """Forget only currently visible turns, never a more privileged speaker's data."""
        current = checked_view(view)
        async with self._lock:
            record = self._satellites.get(eid)
            if not self._loaded or not current or not record or record["binding"] != binding:
                return
            visible = set(current)
            updated = copy.deepcopy(record)
            updated["turns"] = [
                turn for turn in updated["turns"]
                if turn["channel"] != channel or not set(turn["view"]) <= visible
            ]
            choices = updated["choices"]
            if choices and choices["channel"] == channel and set(choices["view"]) <= visible:
                updated["choices"] = {}
            await self._async_replace(eid, updated)
