import json
from pathlib import Path

TRANSLATION = Path("custom_components/codex_assist/translations/en.json")


def test_config_flow_device_step_has_visible_translation_description():
    assert TRANSLATION.exists()

    data = json.loads(TRANSLATION.read_text())
    device_step = data["config"]["step"]["device"]

    assert device_step["title"] == "Sign in with Codex"
    assert "{verification_uri}" in device_step["description"]
    assert "{user_code}" in device_step["description"]
    assert "{interval}" in device_step["description"]


def test_config_flow_errors_are_translated_for_device_polling():
    data = json.loads(TRANSLATION.read_text())
    errors = data["config"]["error"]

    assert "authorization_pending" in errors
    assert "device_code_auth_failed" in errors
    assert "device_code_request_failed" in errors


def test_module_menu_and_learning_setup_are_explicit_and_translated():
    for path in (TRANSLATION, TRANSLATION.parent.parent / "strings.json"):
        config = json.loads(path.read_text())["config"]
        assert set(config["step"]["user"]["menu_options"]) == {"codex", "voice_learning"}
        assert config["step"]["user"]["menu_options"]["voice_learning"] == "Voice Match learning"
        assert "recording consent" in config["step"]["voice_learning"]["description"]
        assert "off by default" in config["step"]["learning_phone"]["description"]
        assert "Sign in" in config["step"]["codex"]["description"]


def test_guidance_and_all_repair_flows_have_matching_translations():
    strings = json.loads((TRANSLATION.parent.parent / "strings.json").read_text())
    assert strings == json.loads(TRANSLATION.read_text())
    assert set(strings["options"]["step"]["init"]["menu_options"]) == {
        "settings", "agents", "voice_match",
    }
    assert "voice_match_cleanup" not in strings["options"]["step"]
    for kind in ("bridge", "source", "entities", "pipeline", "launcher"):
        flow = strings["issues"]["voice_learning_" + kind]["fix_flow"]
        assert {"confirm", "check"} <= set(flow["step"])
        assert "not_resolved" in flow["error"]
        assert {"learning_entry_unavailable", "learning_reconfigure", "learning_options"} <= set(
            flow["abort"]
        )
    menu = strings["options"]["step"]["learning_menu"]["menu_options"]
    assert set(menu) == {
        "learning_status",
        "learning_phone",
        "learning_pairing",
        "learning_personalisation",
    }


def test_shared_prompt_translation_identifies_ai_task_scope():
    data = json.loads(TRANSLATION.read_text())
    settings = data["options"]["step"]["settings"]
    advanced = settings["sections"]["advanced_settings"]

    assert advanced["name"] == "Advanced AI Task settings"
    assert advanced["data"]["prompt"] == "AI Task system prompt"
    assert advanced["data_description"]["prompt"] == (
        "Default instructions used for AI Task requests. "
        "Conversation agents use their own individual system prompts."
    )
