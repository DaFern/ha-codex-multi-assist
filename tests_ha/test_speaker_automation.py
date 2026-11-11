"""Real HA trigger, condition, automation and conversation-response contracts."""

import asyncio

from cryptography.fernet import Fernet
from homeassistant.components import conversation
from homeassistant.core import Context
from homeassistant.helpers import condition, trigger
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.codex_assist import DOMAIN
from custom_components.codex_assist.codex_client import CodexClient, CodexTextDelta
from custom_components.codex_assist.speaker_automation import automations_for_hass
from custom_components.codex_assist.speaker_packet import encode


async def setup_agent(hass, monkeypatch, hass_admin_user):
    assert await async_setup_component(hass, "homeassistant", {})
    key = Fernet.generate_key().decode()
    entry = MockConfigEntry(
        domain=DOMAIN, title="Codex Assist", unique_id=DOMAIN,
        data={"access_token": "test-only", "refresh_token": "test-only", "model": "gpt-5.4"},
        options={"voice_match_pairing_key": key},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    calls = []

    async def reply(self, **kwargs):
        calls.append(kwargs)
        yield CodexTextDelta("Model fallback.")

    monkeypatch.setattr(CodexClient, "stream_turn", reply)
    return key, calls, hass_admin_user.id


def voice_packet(key, user_id, voice="alice", text="good morning"):
    return encode(key, text, voice=voice, revision="a" * 32 if voice else None,
                  ha_user_id=user_id if voice else None)


async def speak(hass, text, context=None):
    return await conversation.async_converse(
        hass, text, None, context or Context(), agent_id="conversation.codex_assist",
    )


async def test_real_automation_choose_speaker_and_return_response(
    hass, monkeypatch, hass_admin_user, hass_read_only_user,
):
    key, model_calls, user_id = await setup_agent(hass, monkeypatch, hass_admin_user)
    account_by_voice = {"alice": user_id, "bob": hass_read_only_user.id}
    seen = []

    async def record(call):
        seen.append((call.data["voice"], call.context))

    hass.services.async_register("test", "record", record)
    assert await async_setup_component(hass, "automation", {"automation": [{
        "id": "speaker_test", "alias": "Speaker test", "mode": "parallel",
        "triggers": [{"trigger": "codex_assist.voice_sentence",
                      "options": {"sentence": ["good morning", "good evening"]}}],
        "actions": [{"choose": [{
            "conditions": [{"condition": "codex_assist.speaker_is",
                            "options": {"voice": name}}],
            "sequence": [
                {"action": "test.record", "data": {"voice": name}},
                {"set_conversation_response": f"Hello {name}."},
            ],
        } for name in ("alice", "bob")], "default": [
            {"set_conversation_response": "General response."},
        ]}],
    }]})
    await hass.async_block_till_done()
    for name in ("alice", "bob", None):
        user_id = account_by_voice.get(name)
        context = Context(user_id=user_id)
        packet = voice_packet(key, user_id, name)
        result = await speak(hass, packet, context)
        assert result.response.speech["plain"]["speech"] == (
            f"Hello {name}." if name else "Model fallback."
        )
        if name:
            assert seen[-1][0] == name
            assert seen[-1][1].parent_id == context.id
            # HA creates the automation action context as a child without
            # copying the original caller's user_id; do not impersonate it.
            assert seen[-1][1].user_id is None
            assert context.user_id == user_id
    assert len(seen) == 2
    assert len(model_calls) == 1
    # Same identity, unrelated phrase; no per-automation profile IDs.
    result = await speak(
        hass, voice_packet(key, account_by_voice["alice"], "alice", "Good evening!"),
        Context(user_id=account_by_voice["alice"]),
    )
    assert result.response.speech["plain"]["speech"] == "Hello alice."
    assert len(seen) == 3
    # An account-bound packet cannot borrow another HA caller's permissions.
    mismatch = await speak(
        hass, voice_packet(key, hass_read_only_user.id, "alice"),
        Context(user_id=account_by_voice["alice"]),
    )
    assert mismatch.response.speech["plain"]["speech"] == "Model fallback."
    assert len(seen) == 3 and len(model_calls) == 2
    # Replays and forged packets cannot execute an automation or reach a model.
    await speak(hass, packet, context)
    await speak(hass, "[[voice-match:v1:invalid]]\ngood morning")
    assert len(seen) == 3 and len(model_calls) == 2
    # A typed/plain request does not borrow the previous speaker or trigger.
    result = await speak(hass, "good morning")
    assert result.response.speech["plain"]["speech"] == "Model fallback."
    assert len(seen) == 3 and len(model_calls) == 3
    assert not automations_for_hass(hass).active


async def test_native_condition_false_for_unrelated_or_manually_supplied_trigger(
    hass, monkeypatch, hass_admin_user,
):
    await setup_agent(hass, monkeypatch, hass_admin_user)
    checker = await condition.async_from_config(hass, {
        "condition": "codex_assist.speaker_is", "options": {"voice": "alice"},
    })
    for variables in ({}, {"trigger": {"platform": "time"}},
                      {"trigger": {"voice_match": {"voice": "alice"}}}):
        assert not checker(hass, variables)
    checker.async_unload()
    # Descriptions resolve via HA's native discovery for the automation editor.
    conditions = await condition.async_get_all_descriptions(hass)
    triggers = await trigger.async_get_all_descriptions(hass)
    assert "codex_assist.speaker_is" in conditions
    assert "codex_assist.voice_sentence" in triggers


async def test_concurrent_requests_do_not_mix_speakers(
    hass, monkeypatch, hass_admin_user, hass_read_only_user,
):
    key, calls, user_id = await setup_agent(hass, monkeypatch, hass_admin_user)
    arrived = asyncio.Event()
    count = 0
    bridge = automations_for_hass(hass)

    async def action(metadata, user_input):
        nonlocal count
        count += 1
        if count == 2:
            arrived.set()
        await arrived.wait()
        assert bridge.speaker_is({"trigger": {"voice_match": metadata}}, metadata["voice"])
        return metadata["voice"]

    remove = bridge.subscribe(["good morning"], action)
    accounts = (user_id, hass_read_only_user.id)
    results = await asyncio.gather(*(
        speak(hass, voice_packet(key, account, name), Context(user_id=account))
        for name, account in zip(("alice", "bob"), accounts, strict=True)
    ))
    assert [r.response.speech["plain"]["speech"] for r in results] == ["alice", "bob"]
    assert not calls and not bridge.active
    remove()


async def test_action_failure_does_not_replay_through_model(hass, monkeypatch, hass_admin_user):
    key, calls, user_id = await setup_agent(hass, monkeypatch, hass_admin_user)
    bridge = automations_for_hass(hass)

    async def fail(metadata, user_input):
        raise RuntimeError("Synthetic private error")

    remove = bridge.subscribe(["good morning"], fail)
    result = await speak(hass, voice_packet(key, user_id), Context(user_id=user_id))
    assert result.response.speech["plain"]["speech"] == (
        "Sorry, I couldn't complete that voice automation."
    )
    assert not calls and not bridge.active
    remove()
