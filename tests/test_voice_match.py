from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from custom_components.codex_assist.speaker_packet import PacketError, decode, encode
from custom_components.codex_assist.voice_match import (
    SpeakerRuntime,
    async_voice_account_matches,
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


def test_uncertain_turns_keep_ordinary_dialogue_but_not_identity_or_preferences():
    key = Fernet.generate_key().decode()
    runtime = SpeakerRuntime()
    content = []
    scopes = []
    for voice in ("alice", None, None, "alice"):
        wire = packet(key, voice=voice)
        content.append(user(wire))
        request = runtime.prepare_request(
            key, wire, content, "one", "jarvis", now=1000
        )
        instructions, boundary, scope = request.instructions, request.boundary, request.scope
        assert len(scoped_contents(content, boundary)) == len(content)
        if voice is None:
            assert not instructions
            assert request.voice is None and request.speaker_name is None
            assert request.ha_user_id is None
        scopes.append(scope)
    assert len(set(scopes)) == 1


@pytest.mark.parametrize("history_item", [
    SimpleNamespace(role="tool_result", content="private calendar result"),
    SimpleNamespace(role="assistant", tool_calls=[object()]),
    SimpleNamespace(role="assistant", native=SimpleNamespace(items=[
        {"type": "function_call_output", "output": "private result"},
    ])),
])
def test_uncertain_turn_does_not_replay_tool_bearing_history(history_item):
    key = Fernet.generate_key().decode()
    runtime = SpeakerRuntime()
    wire = packet(key)
    content = [user(wire)]
    first = runtime.prepare_request(key, wire, content, "chat", "jarvis", now=1000)
    content.extend([history_item, SimpleNamespace(role="assistant", content="What next?")])
    wire = packet(key, voice=None)
    content.append(user(wire))
    neutral = runtime.prepare_request(key, wire, content, "chat", "jarvis", now=1000)
    assert neutral.scope != first.scope
    assert scoped_contents(content, neutral.boundary) == [content[-1]]


def test_neutral_followup_keeps_question_and_same_speaker_return_but_not_other_speaker():
    key = Fernet.generate_key().decode()
    runtime = SpeakerRuntime()
    content = []
    scopes = []
    for voice, text in (("alice", "Help me set up a calendar"),
                        (None, "I use Google"), (None, "How do I connect it?"),
                        ("alice", "Please explain"), ("bob", "What were we discussing?")):
        wire = encode(key, text, voice=voice, revision="a" * 32 if voice else None,
                      now=1000)
        content.append(user(wire))
        request = runtime.prepare_request(key, wire, content, "chat", "jarvis", now=1000)
        scopes.append(request.scope)
        selected = [item.content for item in scoped_contents(content, request.boundary)]
        if voice == "bob":
            assert selected == [text]
        elif len(scopes) > 1:
            assert "Which calendar do you use?" in selected
        content.append(SimpleNamespace(role="assistant", content="Which calendar do you use?"))
    assert len(set(scopes[:4])) == 1
    assert scopes[-1] != scopes[0]


@pytest.mark.parametrize("change", ["agent", "conversation", "key", "expiry", "boundary"])
def test_neutral_continuity_respects_scope_boundaries(change):
    key = Fernet.generate_key().decode()
    runtime = SpeakerRuntime()
    wire = packet(key)
    content = [user(wire)]
    first = runtime.prepare_request(key, wire, content, "chat", "jarvis", now=1000)
    content.append(SimpleNamespace(role="assistant", content="Which calendar?"))
    if change == "boundary":
        content = []
    if change == "key":
        key = Fernet.generate_key().decode()
    now = 1301 if change == "expiry" else 1000
    wire = packet(key, voice=None, now=now)
    content.append(user(wire))
    request = runtime.prepare_request(
        key, wire, content, "other" if change == "conversation" else "chat",
        "friday" if change == "agent" else "jarvis", now=now,
    )
    assert request.scope != first.scope
    assert scoped_contents(content, request.boundary) == [content[-1]]


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


def test_recognised_name_reaches_prompt_without_personal_instructions(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="custom_components.codex_assist.voice_match")
    key = Fernet.generate_key().decode()
    name = 'Alice "Example" {{ 7 * 7 }}'
    wire = encode(key, "hello", voice="alice", revision="a" * 32,
                  speaker_name=name, now=1000)
    assert name not in wire
    request = SpeakerRuntime().prepare_request(
        key, wire, [user(wire)], "chat", "agent", now=1000,
    )
    assert request.verified and request.speaker_name == name
    result = personal_instructions("Original personality", request.instructions,
                                   speaker_name=request.speaker_name,
                                   request_tag=request.diagnostic_tag)
    assert result.startswith("Original personality")
    assert r'Alice \"Example\" {{ 7 * 7 }}' in result
    assert "say you recognise their voice" in result
    assert "not authentication" in result
    assert name not in caplog.text and "Alice" not in caplog.text


def test_account_bound_packet_round_trips_user_id_only_inside_encrypted_payload():
    key = Fernet.generate_key().decode()
    wire = encode(key, "hello", voice="alice", revision="a" * 32,
                  speaker_name="Alice", ha_user_id="ha-user-123", now=1000)
    assert wire.startswith("[[voice-match:v2:")
    assert "ha-user-123" not in wire
    request = SpeakerRuntime().prepare_request(
        key, wire, [user(wire)], "chat", "agent", now=1000,
    )
    assert request.verified and request.ha_user_id == "ha-user-123"


@pytest.mark.parametrize("user_id", ["", "x" * 129, "bad\nuser", 42, []])
def test_account_bound_packet_rejects_invalid_home_assistant_user_ids(user_id):
    with pytest.raises(PacketError):
        encode(Fernet.generate_key().decode(), "hello", voice="alice", revision="a" * 32,
               ha_user_id=user_id)


@pytest.mark.asyncio
async def test_account_binding_requires_same_active_non_system_ha_caller():
    request = SimpleNamespace(verified=True, ha_user_id="ha-user-123")

    class Auth:
        user = SimpleNamespace(id="ha-user-123", is_active=True, system_generated=False)

        async def async_get_user(self, user_id):
            assert user_id == "ha-user-123"
            return self.user

    hass = SimpleNamespace(auth=Auth())
    assert await async_voice_account_matches(
        hass, request, SimpleNamespace(user_id="ha-user-123"),
    )
    assert not await async_voice_account_matches(
        hass, request, SimpleNamespace(user_id="another-user"),
    )
    assert not await async_voice_account_matches(hass, request, SimpleNamespace(user_id=None))
    hass.auth.user = SimpleNamespace(id="ha-user-123", is_active=False,
                                     system_generated=False)
    assert not await async_voice_account_matches(
        hass, request, SimpleNamespace(user_id="ha-user-123"),
    )
    hass.auth.user = SimpleNamespace(id="ha-user-123", is_active=True,
                                     system_generated=True)
    assert not await async_voice_account_matches(
        hass, request, SimpleNamespace(user_id="ha-user-123"),
    )


@pytest.mark.parametrize("name", ["", " ", "x" * 81, "Alice\nAdmin", "A\x00B", 42, []])
def test_packet_rejects_invalid_speaker_names(name):
    with pytest.raises(PacketError):
        encode(Fernet.generate_key().decode(), "hello", voice="alice", revision="a" * 32,
               speaker_name=name)


def test_neutral_packet_cannot_supply_a_name():
    with pytest.raises(PacketError):
        encode(Fernet.generate_key().decode(), "hello", speaker_name="Alice")


def test_speaker_name_preserves_full_preference_limit_and_literal_unicode():
    key = Fernet.generate_key().decode()
    name = "É" * 80
    preferences = "🙂" * 2000
    wire = encode(key, "hello", voice="alice", revision="a" * 32,
                  instructions=preferences, speaker_name=name, now=1000)
    _, payload, _ = decode(key, wire, now=1000)
    assert payload["speaker_name"] == name
    assert payload["instructions"] == preferences


def test_name_is_request_local_and_legacy_packets_still_work():
    key = Fernet.generate_key().decode()
    runtime = SpeakerRuntime()
    contents = []
    scopes = []
    for voice, name in (("alice", "Alice"), ("alice", "Alicia"), ("bob", "Bob"),
                        (None, None), ("bob", None)):
        wire = encode(key, "hello", voice=voice, revision="a" * 32 if voice else None,
                      speaker_name=name, now=1000)
        contents.append(user(wire))
        request = runtime.prepare_request(key, wire, contents, "chat", "agent", now=1000)
        assert request.speaker_name == name
        scopes.append(request.scope)
        result = personal_instructions("Base", "", speaker_name=request.speaker_name)
        if name is None:
            assert result == "Base"
        else:
            assert name in result
    assert scopes[3] == scopes[2]  # Neutral continuity carries no current identity.
    assert len(set(scopes)) == len(scopes) - 1
    plain = runtime.prepare_request(key, "hello", [user("hello")], "chat", "agent", now=1000)
    assert plain.speaker_name is None and not plain.verified


def test_diagnostic_tag_contains_no_text_and_survives_valid_packet_transport():
    from custom_components.codex_assist.speaker_packet import diagnostic_tag

    key = Fernet.generate_key().decode()
    wire = packet(key)
    tag = diagnostic_tag(wire)
    assert len(tag) == 16 and all(char in "0123456789abcdef" for char in tag)
    runtime = SpeakerRuntime()
    request = runtime.prepare_request(key, wire, [user(wire)], "chat", "agent", now=1000)
    assert request.diagnostic_tag == tag
    clean_request = SpeakerRuntime().prepare_request(
        key, "hello", [user("hello")], "chat", "agent", now=1000, packet_text=wire,
    )
    assert clean_request.diagnostic_tag == tag
    assert diagnostic_tag("private spoken plain text") is None
    assert diagnostic_tag("[[voice-match:v1:bad") is None
    assert diagnostic_tag("[[voice-match:v1:\ud800]]\nhello") is None
    assert diagnostic_tag("[[voice-match:v1:" + "x" * 40000 + "]]\nhello") is None


def test_prompt_diagnostics_log_only_tag_and_application_flag(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="custom_components.codex_assist.voice_match")
    result = personal_instructions("Private base prompt", "Private personal preference",
                                   request_tag="a" * 16)
    assert "Private personal preference" in result
    result = personal_instructions("Private base prompt", "", request_tag="b" * 16)
    assert result == "Private base prompt"
    output = "\n".join(record.getMessage() for record in caplog.records)
    assert "request=" + "a" * 16 in output and "instructions_applied=True" in output
    assert "request=" + "b" * 16 in output and "instructions_applied=False" in output
    assert "Private base prompt" not in output and "Private personal preference" not in output


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


@pytest.mark.asyncio
async def test_clean_task_capacity_fails_without_evicting_active_requests():
    import asyncio

    runtime = SpeakerRuntime()
    runtime.clean_tasks.update(object() for _ in range(256))
    with pytest.raises(PacketError):
        runtime.track_clean_task(asyncio.current_task())
    assert len(runtime.clean_tasks) == 256


@pytest.mark.asyncio
async def test_clean_shutdown_clears_carriers_timers_and_only_cancels_owned_tasks():
    import asyncio

    runtime = SpeakerRuntime()
    ready = asyncio.Event()
    block = asyncio.Event()
    key = Fernet.generate_key().decode()
    runtime.seen["existing-replay-record"] = 2000
    retained = []

    async def clean_request():
        runtime.track_clean_task(asyncio.current_task())
        retained.append(runtime.handoffs.issue(key, packet(key), now=1000))
        ready.set()
        await block.wait()

    owned = asyncio.create_task(clean_request())
    plain = asyncio.create_task(block.wait())
    await ready.wait()
    pending = list(runtime.handoffs.pending.values())
    await runtime.async_stop_clean_requests()
    assert owned.cancelled() and not plain.cancelled()
    assert not runtime.handoffs.pending and not runtime.clean_tasks
    assert all(record.timer.cancelled() for record in pending)
    assert runtime.seen == {"existing-replay-record": 2000}
    assert runtime.clean_generation == 1
    with pytest.raises(PacketError):
        runtime.handoffs.consume(key, retained[0], now=1000)
    block.set()
    await plain
