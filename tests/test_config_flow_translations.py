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
