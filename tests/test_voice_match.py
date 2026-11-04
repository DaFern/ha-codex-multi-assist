from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from custom_components.codex_assist.speaker_packet import PacketError, decode, encode
from custom_components.codex_assist.voice_match import (
    SpeakerRuntime,
    personal_instructions,
    scoped_contents,
)


def user(text):
    return SimpleNamespace(role="user", content=text)


def packet(key, voice="alice", instructions="Be brief", now=1000, revision="a" * 32):
    return encode(key, "hello", voice=voice, revision=revision if voice else None,
                  instructions=instructions if voice else "", now=now)


def test_packet_rejects_expiry_tampering_and_wrong_key():
    key = Fernet.generate_key().decode()
    wire = packet(key)
    assert decode(key, wire, now=1000)[0] == "hello"
    assert "Be brief" not in wire
    cases = (
        (key, wire, 1201), (key, wire.replace("hello", "other"), 1000),
        (Fernet.generate_key().decode(), wire, 1000), (key, "[alice] hello", 1000),
    )
    for other_key, text, now in cases:
        with pytest.raises(PacketError):
            decode(other_key, text, now=now)


def test_replay_cannot_select_another_agent_or_conversation():
    key = Fernet.generate_key().decode()
    runtime = SpeakerRuntime()
    wire = packet(key)
    content = [user(wire)]
    runtime.prepare(key, wire, content, "one", "jarvis", now=1000)
    with pytest.raises(PacketError):
        runtime.prepare(key, wire, [user(wire)], "two", "friday", now=1000)


def test_switching_people_and_returning_does_not_recover_old_history():
    key = Fernet.generate_key().decode()
    runtime = SpeakerRuntime()
    content = []
    scopes = []
    for name in ("alice", "bob", "alice"):
        wire = packet(key, voice=name)
        content.append(user(wire))
        clean, instructions, boundary, scope = runtime.prepare(
            key, wire, content, "shared", "jarvis", now=1000
        )
        assert clean == "hello"
        assert instructions == "Be brief"
        scopes.append(scope)
        selected = scoped_contents(content, boundary)
        assert len(selected) == 1
        assert selected[0].content == "hello"
        content.append(SimpleNamespace(role="assistant", content=f"private {name}"))
    assert len(set(scopes)) == 3


def test_same_person_same_active_conversation_keeps_only_current_scope():
    key = Fernet.generate_key().decode()
    runtime = SpeakerRuntime()
    first = packet(key)
    content = [user("old unrelated"), user(first)]
    _, _, boundary, scope = runtime.prepare(key, first, content, "one", "jarvis", now=1000)
    content.append(SimpleNamespace(role="assistant", content="our reply"))
    second = packet(key)
    content.append(user(second))
    _, _, boundary2, scope2 = runtime.prepare(key, second, content, "one", "jarvis", now=1000)
    assert boundary2 is boundary
    assert scope2 == scope
    assert [item.content for item in scoped_contents(content, boundary2)] == [
        "hello", "our reply", "hello",
    ]


def test_uncertain_turns_start_fresh_and_do_not_reuse_preferences():
    key = Fernet.generate_key().decode()
    runtime = SpeakerRuntime()
    content = []
    scopes = []
    for voice in ("alice", None, None):
        wire = packet(key, voice=voice)
        content.append(user(wire))
        _, instructions, boundary, scope = runtime.prepare(
            key, wire, content, "one", "jarvis", now=1000
        )
        assert len(scoped_contents(content, boundary)) == 1
        if voice is None:
            assert not instructions
        scopes.append(scope)
    assert len(set(scopes)) == 3


def test_agents_conversations_preference_changes_and_idle_expiry_reset_scope():
    key = Fernet.generate_key().decode()
    runtime = SpeakerRuntime()
    content = []
    scopes = []
    for conversation, agent, revision, now in (
        ("one", "jarvis", "a" * 32, 1000), ("one", "friday", "a" * 32, 1000),
        ("two", "friday", "a" * 32, 1000), ("two", "friday", "b" * 32, 1000),
        ("two", "friday", "b" * 32, 1301),
    ):
        wire = packet(key, now=now, revision=revision)
        content.append(user(wire))
        scopes.append(runtime.prepare(key, wire, content, conversation, agent, now=now)[3])
    assert len(set(scopes)) == 5


def test_unpaired_plain_requests_remain_unchanged_and_tagged_requests_fail_closed():
    runtime = SpeakerRuntime()
    content = [user("hello")]
    assert runtime.prepare("", "hello", content, "one", "jarvis") == ("hello", "", None, None)
    key = Fernet.generate_key().decode()
    with pytest.raises(PacketError):
        runtime.prepare("", packet(key), content, "one", "jarvis", now=1000)


def test_personal_instructions_are_literal_and_do_not_replace_base():
    personal = "Call me Alice. {{ states('sensor.private') }}"
    result = personal_instructions("Original personality and tools", personal)
    assert result.startswith("Original personality and tools")
    assert personal in result
    assert "not authentication or permission" in result


def test_live_replay_cache_never_evicts_records_to_accept_more_requests():
    runtime = SpeakerRuntime()
    runtime.seen.update({str(index): 2000 for index in range(4096)})
    key = Fernet.generate_key().decode()
    wire = packet(key)
    with pytest.raises(PacketError):
        runtime.prepare(key, wire, [user(wire)], "one", "jarvis", now=1000)


def test_mismatched_chat_turn_cannot_be_overwritten_by_another_request():
    key = Fernet.generate_key().decode()
    wire = packet(key)
    content = [user("somebody else's current turn")]
    with pytest.raises(PacketError):
        SpeakerRuntime().prepare(key, wire, content, "one", "jarvis", now=1000)
    assert content[0].content == "somebody else's current turn"


def test_history_snapshot_excludes_a_later_concurrent_user_turn():
    first = user("mine")
    content = [
        first, SimpleNamespace(role="assistant", content="my reply"), user("another request"),
    ]
    assert [item.content for item in scoped_contents(content, first, first)] == ["mine", "my reply"]


def test_pairing_key_is_redacted_from_diagnostics():
    from custom_components.codex_assist.diagnostics import REDACTED, redact_sensitive

    key = Fernet.generate_key().decode()
    result = redact_sensitive({"voice_match_pairing_key": key, "model": "unchanged"})
    assert result["voice_match_pairing_key"] == REDACTED
    assert key not in repr(result)


def test_unknown_packet_versions_fail_closed_even_if_connector_is_disabled():
    wire = "[[voice-match:v2:unsupported]]\nhello"
    with pytest.raises(PacketError):
        SpeakerRuntime().prepare("", wire, [user(wire)], "one", "jarvis")


def test_invalidated_scope_cannot_recover_old_speaker_history():
    key = Fernet.generate_key().decode()
    runtime = SpeakerRuntime()
    first = packet(key)
    contents = [user(first)]
    old_scope = runtime.prepare(key, first, contents, "one", "jarvis", now=1000)[3]
    runtime.invalidate("one")
    contents.append(user("[[voice-match:v1:bad]]\nhello"))
    fresh = packet(key)
    contents.append(user(fresh))
    _, _, boundary, scope = runtime.prepare(key, fresh, contents, "one", "jarvis", now=1000)
    assert scope != old_scope
    assert len(scoped_contents(contents, boundary)) == 1


def test_disabling_pairing_cannot_restore_previously_mixed_history():
    key = Fernet.generate_key().decode()
    runtime = SpeakerRuntime()
    wire = packet(key)
    contents = [user(wire)]
    old_scope = runtime.prepare(key, wire, contents, "one", "jarvis", now=1000)[3]
    contents.append(SimpleNamespace(role="assistant", content="private previous answer"))
    contents.append(user("plain request after disabling"))
    _, instructions, boundary, scope = runtime.prepare(
        "", "plain request after disabling", contents, "one", "jarvis", now=1000
    )
    assert instructions == ""
    assert scope != old_scope
    assert [item.content for item in scoped_contents(contents, boundary)] == [
        "plain request after disabling"
    ]
