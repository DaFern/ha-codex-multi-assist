"""Outbound guidance and native HA routing with scripted HTTPX responses.

The response script does not inspect instructions or simulate model compliance.
These tests cannot establish live model behavior or satellite microphone state.
"""

import json
from copy import deepcopy

import pytest
from homeassistant.components import ai_task, conversation
from homeassistant.components.conversation.chat_log import async_subscribe_chat_logs
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_web_search_delivery import (
    COMPLETED,
    call_event,
    message,
    model_round,
    search_reply,
    text_events,
)
from test_web_search_delivery import backend as backend

from custom_components.codex_assist import DOMAIN


@pytest.fixture
def entry_settings():
    return {}, {}


@pytest.fixture
def web_search():
    return False


@pytest.fixture
async def clarification_entry(hass, entry_settings, web_search):
    assert await async_setup_component(hass, "homeassistant", {})
    data, options = entry_settings
    entry = MockConfigEntry(
        domain=DOMAIN, title="Codex Assist", unique_id=DOMAIN,
        data={"access_token": "test-access", "refresh_token": "test-refresh",
              "model": "gpt-5.4", **data},
        options={"web_search": web_search, **options},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def assert_clarification_guidance(instructions):
    for requirement in (
        "When clarification is required, ask one concise, direct question",
        "as the final sentence",
        "appropriate question mark for the user's language and nothing after it",
        "Resolve ambiguous actions or targets before executing them",
        "Do not add unnecessary closing questions after ordinary answers, "
        "completed actions, or cancellation",
    ):
        assert instructions.count(requirement) == 1


def assert_search_speech_guidance(instructions, enabled):
    for requirement in (
        "do not include raw URLs, markdown links, or a Source/Sources section",
        "Refer to sources by human-readable names only.",
    ):
        assert instructions.count(requirement) == int(enabled)
    assert "renders structured citations separately" not in instructions


@pytest.mark.parametrize("web_search", [False, True])
@pytest.mark.parametrize(("entry_settings", "expected", "absent"), [
    (({}, {}), "You are a concise Home Assistant Assist conversation agent.", None),
    (({"prompt": "Use short replies."}, {}), "Use short replies.", None),
    (({"prompt": "Old data prompt."}, {"prompt": "Options prompt."}),
     "Options prompt.", "Old data prompt."),
    (({}, {"prompt": "Template language {{ llm_context.language }}."}),
     "Template language el.", "{{"),
])
async def test_outbound_clarification_guidance_preserves_ha_prompt(
    hass, clarification_entry, backend, request, expected, absent, web_search,
):
    planned, requests = backend
    stored = deepcopy((dict(clarification_entry.data), dict(clarification_entry.options)))
    chat_logs = []
    request.addfinalizer(async_subscribe_chat_logs(
        hass, lambda conversation_id, event_type, data: (
            chat_logs.append(data["chat_log"]) if "chat_log" in data else None
        ),
    ))
    conversation_id = None
    for _ in range(2):
        model_round(planned, text_events("A plain answer.") + [COMPLETED])
        result = await conversation.async_converse(
            hass, "Give a test answer.", conversation_id, Context(), language="el",
            agent_id="conversation.codex_assist",
            extra_system_prompt="Extra pipeline prompt." if conversation_id is None else None,
        )
        conversation_id = result.conversation_id
        system = chat_logs[-1]["content"][0]["content"]
        instructions = requests[-1][1]["instructions"]
        assert expected in system
        assert "Extra pipeline prompt." in system
        assert "When clarification is required" not in system
        assert_clarification_guidance(instructions)
        assert instructions.startswith(system + "\n\n")
        if absent is not None:
            assert absent not in instructions
        assert_search_speech_guidance(instructions, web_search)
    assert (dict(clarification_entry.data), dict(clarification_entry.options)) == stored
    assert len(requests) == 2


@pytest.mark.parametrize(("reply", "language", "continues"), [
    ("Which light?", "en", True),
    ("Ποιο φως;", "el", True),
    ("どのライトですか？", "ja", True),
    ("The temperature is twenty degrees.", "en", False),
    ("The light is on.", "en", False),
    ("Cancelled.", "en", False),
    ("Did you mean the first light...", "en", False),
    ("Did you mean the first light.", "en", False),
    ("Which light? I will wait.", "en", False),
    ('"Which light?"', "en", False),
    ("أي ضوء؟", "ar", False),
])
async def test_native_ha_continuation_keeps_scripted_text_and_history(
    hass, clarification_entry, backend, reply, language, continues,
):
    planned, requests = backend
    model_round(planned, text_events(reply) + [COMPLETED])
    result = await conversation.async_converse(
        hass, "Give a test response.", None, Context(), language=language,
        agent_id="conversation.codex_assist",
    )
    assert result.response.speech["plain"]["speech"] == reply
    assert result.continue_conversation is continues
    assert result.conversation_id
    if continues:
        model_round(planned, text_events("Understood.") + [COMPLETED])
        followup = await conversation.async_converse(
            hass, "The first one.", result.conversation_id, Context(), language=language,
            agent_id="conversation.codex_assist",
        )
        assert followup.conversation_id == result.conversation_id
        assert followup.continue_conversation is False
        assert requests[-1][1]["input"] == [
            {"role": "user", "content": "Give a test response."},
            message(reply),
            {"role": "user", "content": "The first one."},
        ]


@pytest.mark.parametrize("web_search", [True])
async def test_recovered_question_keeps_native_continuation_without_source_card(
    hass, clarification_entry, backend,
):
    planned, requests = backend
    model_round(planned, [call_event("search-1", "web_search", {"queries": ["synthetic"]}),
                          COMPLETED])
    search_reply(planned)
    question = "Which documentation page?"
    model_round(planned, [
        {"type": "response.output_item.done", "item": message(question)}, COMPLETED,
    ])
    result = await conversation.async_converse(
        hass, "Find the documentation.", None, Context(), agent_id="conversation.codex_assist",
    )
    assert result.response.speech["plain"]["speech"] == question
    assert result.continue_conversation is True
    assert not result.response.card
    for path, payload in requests:
        if path.endswith("/responses"):
            assert_clarification_guidance(payload["instructions"])
            assert_search_speech_guidance(payload["instructions"], True)


@pytest.mark.parametrize("web_search", [False, True])
@pytest.mark.parametrize("native_followup", [True, False])
async def test_clarification_then_native_action_preserves_guidance_through_retry_and_handoff(
    hass, clarification_entry, backend, web_search, native_followup, monkeypatch,
):
    """A fixed script proves routing only, not that the model waits for clarification."""
    executed = []

    async def turn_on(call):
        executed.append(call.data)

    hass.services.async_register("light", "turn_on", turn_on)
    for name in ("alpha", "beta"):
        entity_id = f"light.test_{name}"
        hass.states.async_set(entity_id, "off", {"friendly_name": f"Test {name}"})
        async_expose_entity(hass, "conversation", entity_id, True)

    planned, requests = backend
    planned.append(("/backend-api/codex/responses", 401, {"error": "Synthetic rejection"}))
    planned.append(("/oauth/token", 200, {
        "access_token": "test-new-access", "refresh_token": "test-new-refresh",
    }))
    question = "Which light, Test alpha or Test beta?"
    model_round(planned, text_events(question) + [COMPLETED])
    result = await conversation.async_converse(
        hass, "Turn on the test light.", None, Context(), agent_id="conversation.codex_assist",
    )
    assert result.response.speech["plain"]["speech"] == question
    assert result.continue_conversation is True
    assert executed == []

    # Older HA does not recognise a bare target as a continuation. Exercise
    # both the portable explicit native command and an unrecognised follow-up
    # that requires the model to request a real authorised action.
    followup_text = "Turn on Test alpha." if native_followup else "Test alpha."
    with monkeypatch.context() as patch:
        if not native_followup:
            agent = conversation.async_get_agent(hass, conversation.HOME_ASSISTANT_AGENT)

            async def unrecognised(user_input, *, strict_intents_only):
                assert user_input.text == followup_text
                assert strict_intents_only is True
                return None

            patch.setattr(agent, "async_recognize_intent", unrecognised)
            turn_on_tool = next(
                tool["name"] for tool in requests[-1][1]["tools"]
                if tool["name"].endswith("HassTurnOn")
            )
            model_round(planned, [call_event("action-1", turn_on_tool, {
                "name": "Test alpha", "domain": ["light"],
            }), COMPLETED])
        model_round(planned, text_events(json.dumps({
            "outcome": "accepted",
            "reply": "Test alpha: request accepted; its state is unconfirmed.",
        })) + [COMPLETED])
        followup = await conversation.async_converse(
            hass, followup_text, result.conversation_id, Context(),
            agent_id="conversation.codex_assist",
        )
    assert followup.conversation_id == result.conversation_id
    assert followup.continue_conversation is False
    assert followup.response.speech["plain"]["speech"] == (
        "Test alpha: request accepted; its state is unconfirmed."
    )
    assert len(executed) == 1, requests[-1][1]["input"][-1]
    assert executed[0]["entity_id"] == ["light.test_alpha"]
    followup_requests = 3 if native_followup else 4
    assert len([payload for path, payload in requests if path.endswith("/responses")]) == (
        followup_requests
    )
    model_round(planned, text_events("A follow-up answer.") + [COMPLETED])
    later = await conversation.async_converse(
        hass, "Give a test answer.", followup.conversation_id, Context(),
        agent_id="conversation.codex_assist",
    )
    assert later.response.speech["plain"]["speech"] == "A follow-up answer."
    assert len(executed) == 1
    model_requests = [payload for path, payload in requests if path.endswith("/responses")]
    assert len(model_requests) == followup_requests + 1
    for payload in model_requests:
        assert_clarification_guidance(payload["instructions"])
        is_reply = payload.get("text", {}).get("format", {}).get("name") == (
            "action_acknowledgement"
        )
        assert_search_speech_guidance(payload["instructions"], web_search and not is_reply)
        if is_reply:
            assert payload.get("tools", []) == []
    assert model_requests[0]["instructions"] == model_requests[1]["instructions"]
    assert model_requests[-1]["input"][:3] == [
        {"role": "user", "content": "Turn on the test light."},
        message(question),
        {"role": "user", "content": followup_text},
    ]
    outputs = [item for item in model_requests[-1]["input"]
               if item.get("type") == "function_call_output"]
    assert len(outputs) == 1
    native_calls = [item for item in model_requests[-1]["input"]
                    if item.get("type") == "function_call"]
    assert len(native_calls) == 1
    assert native_calls[0]["name"].endswith("HassTurnOn")
    assert outputs[0]["call_id"] == native_calls[0]["call_id"]


@pytest.mark.parametrize("web_search", [False, True])
async def test_ai_task_does_not_receive_conversation_clarification_guidance(
    hass, clarification_entry, backend,
):
    planned, requests = backend
    model_round(planned, text_events("A task answer.") + [COMPLETED])
    result = await ai_task.async_generate_data(
        hass, task_name="Test", instructions="Summarize the task.",
        entity_id="ai_task.codex_assist_ai_task",
    )
    assert result.data == "A task answer."
    assert len(requests) == 1
    instructions = requests[0][1]["instructions"]
    assert instructions
    assert requests[0][1]["input"] == [{"role": "user", "content": "Summarize the task."}]
    assert "When clarification is required" not in instructions
    assert "Resolve ambiguous actions or targets" not in instructions


@pytest.mark.parametrize("domain,service,state,attributes,sentence", [
    ("light", "turn_off", "on", {}, "Turn off Test device"),
    ("switch", "turn_off", "on", {}, "Turn off Test device"),
    ("fan", "turn_off", "on", {}, "Turn off Test device"),
    ("lock", "lock", "unlocked", {}, "Lock Test device"),
    ("cover", "close_cover", "open", {"device_class": "blind"}, "Close Test device"),
    ("climate", "set_temperature", "heat", {
        "temperature": 18, "min_temp": 7, "max_temp": 35, "supported_features": 1,
    },
     "Set Test device temperature to 21 degrees"),
    ("media_player", "media_pause", "playing", {"supported_features": 1}, "Pause Test device"),
    ("scene", "turn_on", "unknown", {}, "Activate Test device"),
    ("script", "turn_on", "off", {}, "Run Test device"),
])
@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("agent_id,entry_settings", [
    ("conversation.codex_assist", ({}, {})), ("conversation.jarvis", ({}, {})),
    ("conversation.f_r_i_d_a_y", ({}, {})), ("conversation.ultron", ({}, {})),
    ("conversation.navigator", ({}, {"agents": [{
        "id": "custom-navigator", "name": "Navigator", "prompt": "Speak in nautical metaphors.",
        "model": "gpt-5.4", "reasoning_effort": "low", "reasoning_summary": "auto",
        "text_verbosity": "low", "web_search": False,
    }]})),
])
async def test_native_control_uses_selected_personality_without_reexecuting_actions(
    hass, clarification_entry, monkeypatch, domain, service, state, attributes, sentence,
    fails, agent_id,
):
    from custom_components.codex_assist.codex_client import CodexClient, CodexTextDelta

    assert await async_setup_component(hass, domain, {})
    await hass.async_block_till_done()
    executed = []

    async def handle(call):
        executed.append(call.data)
        if fails:
            raise HomeAssistantError("Synthetic device failure")

    # Acknowledge handling without pretending physical completion. In particular
    # a cover can be moving, and scripts/scenes have no universal final state.
    hass.services.async_register(domain, service, handle)
    hass.states.async_set(f"{domain}.test", state, {"friendly_name": "Test device", **attributes})
    async_expose_entity(hass, "conversation", f"{domain}.test", True)

    requests = []

    async def styled_reply(*args, **kwargs):
        requests.append(kwargs)
        assert len(executed) == 1
        assert kwargs["tools"] == []
        payload = json.loads(kwargs["input_items"][0]["content"])
        assert payload["outcome"] == ("failed" if fails else "accepted")
        if not fails:
            assert payload["targets"][0]["name"] == "Test device"
            assert payload["targets"][0]["verification"] not in {
                "reported_requested_state", "reported_requested_setting",
            }  # This fixture deliberately acknowledges without updating state.
        yield CodexTextDelta(json.dumps({
            "outcome": payload["outcome"], "reply": (
                "Test device: alas, the request could not be carried out." if fails
                else "Test device: request received, but its resulting state is unconfirmed."
            ),
        }))

    monkeypatch.setattr(CodexClient, "stream_turn", styled_reply)
    result = await conversation.async_converse(
        hass, sentence, None, Context(), language="en", agent_id=agent_id,
    )
    assert len(executed) == 1, result.response.as_dict()
    expected = ("Test device: alas, the request could not be carried out." if fails
                else "Test device: request received, but its resulting state is unconfirmed.")
    assert result.response.speech["plain"]["speech"] == expected
    assert len(requests) == 1
    selected = conversation.async_get_agent(hass, agent_id)
    assert selected.profile.prompt in requests[0]["instructions"]
    assert "Synthetic device failure" not in str(requests)


async def test_group_alias_without_area_executes_instead_of_text_only_false_success(
    hass, clarification_entry, monkeypatch, hass_admin_user,
):
    from homeassistant.helpers import entity_registry as er

    from custom_components.codex_assist.codex_client import CodexClient, CodexTextDelta

    registry = er.async_get(hass)
    entry = registry.async_get_or_create("light", "test", "group", original_name="Study")
    registry.async_update_entity(entry.entity_id, aliases={"Study lights"})
    hass.states.async_set(entry.entity_id, "on", {"friendly_name": "Study"})
    async_expose_entity(hass, "conversation", entry.entity_id, True)
    executed = []
    callers = []

    async def turn_off(call):
        executed.append(call.data)
        callers.append(call.context.user_id)
        hass.states.async_set(entry.entity_id, "off", {"friendly_name": "Study"})

    hass.services.async_register("light", "turn_off", turn_off)

    async def false_success(*args, **kwargs):
        yield CodexTextDelta("The lights are off.")

    monkeypatch.setattr(CodexClient, "stream_turn", false_success)
    result = await conversation.async_converse(
        hass, "Turn off the Study lights.", None, Context(user_id=hass_admin_user.id),
        language="en", agent_id="conversation.ultron",
    )
    assert result.response.speech["plain"]["speech"] != "The lights are off."
    assert len(executed) == 1
    assert callers == [hass_admin_user.id]
    assert executed[0]["entity_id"] == [entry.entity_id]
    assert hass.states.get(entry.entity_id).state == "off"
    assert result.response.speech["plain"]["speech"] == "I've turned Study off."


@pytest.mark.parametrize("model_path", [False, True])
@pytest.mark.parametrize("delayed", [False, True])
async def test_device_specific_reply_uses_exact_native_result_and_state_feedback(
    hass, clarification_entry, monkeypatch, model_path, delayed,
):
    import asyncio

    from custom_components.codex_assist.codex_client import (
        CodexClient,
        CodexTextDelta,
        CodexToolCall,
        CodexToolCallDelta,
    )

    executed = []
    updates = []
    eid = "light.readback_test"
    hass.states.async_set(eid, "on", {"friendly_name": "Test lamp"})
    async_expose_entity(hass, "conversation", eid, True)

    async def update():
        if delayed:
            await asyncio.sleep(0.02)
        hass.states.async_set(eid, "off", {"friendly_name": "Test lamp"})

    async def turn_off(call):
        executed.append(call.data)
        if delayed:
            updates.append(asyncio.create_task(update()))
        else:
            await update()

    hass.services.async_register("light", "turn_off", turn_off)
    requests = []

    async def model(self, **kwargs):
        requests.append(kwargs)
        if kwargs["tools"]:
            tool = next(t["name"] for t in kwargs["tools"] if t["name"].endswith("HassTurnOff"))
            yield CodexToolCallDelta(CodexToolCall(
                id="one", name=tool, arguments={"name": "Test lamp", "domain": ["light"]},
            ))
            return
        assert len(executed) == 1
        payload = json.loads(kwargs["input_items"][0]["content"])
        target, = payload["targets"]
        assert target["name"] == "Test lamp" and target["domain"] == "light"
        assert target["command_result"] == "accepted"
        assert target["verification"] == "reported_requested_state"
        assert target["reported_state"] == target["expected_state"] == "off"
        assert target["reply_status"] == "success"
        assert "entity_id" not in target
        assert kwargs["instructions"].startswith("You are J.A.R.V.I.S.")
        yield CodexTextDelta(json.dumps({
            "outcome": "accepted", "reply": "I've turned Test lamp off. Sensibly economical.",
        }))

    monkeypatch.setattr(CodexClient, "stream_turn", model)
    if model_path:
        agent = conversation.async_get_agent(hass, conversation.HOME_ASSISTANT_AGENT)

        async def unrecognised(*args, **kwargs):
            return None

        monkeypatch.setattr(agent, "async_recognize_intent", unrecognised)
    try:
        result = await conversation.async_converse(
            hass, "Turn off Test lamp", None, Context(), agent_id="conversation.jarvis",
        )
    finally:
        await asyncio.gather(*updates)
    assert result.response.speech["plain"]["speech"] == (
        "I've turned Test lamp off. Sensibly economical."
    )
    assert len(executed) == 1
    assert requests[-1]["tools"] == []
    assert len(requests) == (2 if model_path else 1)


async def test_unexposed_target_cannot_be_controlled_by_native_or_model_path(
    hass, clarification_entry, monkeypatch,
):
    from custom_components.codex_assist.codex_client import (
        CodexClient,
        CodexToolCall,
        CodexToolCallDelta,
    )

    executed = []
    requests = []

    async def turn_off(call):
        executed.append(call)

    hass.services.async_register("light", "turn_off", turn_off)
    hass.states.async_set("light.hidden", "on", {"friendly_name": "Hidden device"})
    async_expose_entity(hass, "conversation", "light.hidden", False)

    async def forbidden_call(*args, **kwargs):
        requests.append(kwargs)
        yield CodexToolCallDelta(CodexToolCall(
            id="hidden-attempt", name="HassTurnOff",
            arguments={"name": "Hidden device", "domain": ["light"]},
        ))

    monkeypatch.setattr(CodexClient, "stream_turn", forbidden_call)
    result = await conversation.async_converse(
        hass, "Turn off Hidden device.", None, Context(), language="en",
        agent_id="conversation.ultron",
    )
    assert len(requests) == 2
    assert executed == []
    assert hass.states.get("light.hidden").state == "on"
    assert result.response.speech["plain"]["speech"] == (
        "Sorry, Home Assistant couldn't complete that request."
    )
