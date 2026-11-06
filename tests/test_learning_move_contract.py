"""Pin safety-critical moved logic to the reviewed 0.4.5 companion, not a sibling checkout."""

import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/codex_assist/learning"
# AST hashes from the standalone companion in add-on release 7ce8f71. Formatting
# may change; consent, handoff, cleanup, transport and diagnostic logic may not
# change accidentally during a namespace/lifecycle move.
SOURCE_AST = {
    "phone_flow.py": "84d102d99723d35011b9c84032927a2097dbd959b557dae1e71c8ce12feddd58",
    "phone_handoff.py": "493ac6fe362b36524f95cdbf37db32bdedd91d46d827baf1ebd5a77e75958d89",
    "phone_diagnostics.py": "3bb7c0187683c8697b9c4f47f1087e036f6f0e88d93455f7406b4adb15006ccc",
    "coordinator.py": "6e1b42b8b8d68240dcfda5e07c08fc4841458397afd7417907bb0b7a77c9aa33",
    "bridge_client.py": "217999906d27bf60c7e91645197e05064690b4efe359b4b25a6ba3a13ecd44fd",
}
# Approved post-move diagnostic-only extension: append the allowlisted STT
# cancellation stage. Keep the original hash above as provenance; all other
# consent/transport/handoff source pins remain unchanged.
DIAGNOSTIC_AST = "60fb6b04e9b8c74896c4f467592d5bf6f3fe1067313cde9f2b4f3e1838c965e8"

# Approved presentation-only extension. Removing precisely these six literal
# suffixes must restore the original AST, including every consent/control branch.
ASSISTANT_REMINDER = (
    " If you're finished with voice learning, remember to switch back to your regular assistant."
)
REMINDER_RESPONSES = Counter(
    {
        (
            "Voice learning cancelled. This unfinished session's recordings were deleted. "
            "Your existing voiceprint is unchanged."
        ): 2,
        (
            "Voice learning cancelled. No learning started in this conversation. "
            "Any earlier paused recordings are unchanged."
        ): 1,
        (
            "Your replacement voiceprint validated and the saved samples were cleaned up. "
            "Voice learning is complete."
        ): 1,
        "Voice learning is paused. Partial samples are kept for an explicitly consented resume.": 1,
        (
            "That sounded like a learning control, so it was not saved. "
            "Learning is paused and unfinished recordings are kept. "
            "Ask to continue when you're ready."
        ): 1,
    }
)


@pytest.mark.parametrize("name", SOURCE_AST)
def test_safety_logic_matches_reviewed_source(name):
    parsed = ast.parse((ROOT / name).read_text())
    if name == "phone_flow.py":
        # The approved wait delegates read-only polling to a separately tested
        # helper. Remove only this exact import/call/recheck, not arbitrary code.
        extension_import = ast.parse("from .finalization import wait_for_final_state").body[0]
        imports = [node for node in parsed.body if ast.dump(node) == ast.dump(extension_import)]
        assert len(imports) == 1
        parsed.body.remove(imports[0])
        controller = next(
            node
            for node in parsed.body
            if isinstance(node, ast.ClassDef) and node.name == "PhoneController"
        )
        next_method = next(
            node
            for node in controller.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_next"
        )
        extension = ast.parse(
            "state = await wait_for_final_state(self, flow, frame, state)\nself.check(frame)"
        ).body
        assert [ast.dump(node) for node in next_method.body[2:4]] == [
            ast.dump(node) for node in extension
        ]
        del next_method.body[2:4]
        new_processing = (
            "Your voice recording is still processing. This check has ended. "
            "Check Voice Match management, or ask for status. Do not read another sample yet."
        )
        processing_changes = 0
        found = Counter()
        for node in ast.walk(parsed):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value == new_processing:
                    processing_changes += 1
                    node.value = (
                        "Processing your voice recording. Please wait, then ask for status. "
                        "Do not read another sample yet."
                    )
                if node.value.endswith(ASSISTANT_REMINDER):
                    original = node.value.removesuffix(ASSISTANT_REMINDER)
                    found[original] += 1
                    node.value = original
        assert found == REMINDER_RESPONSES
        assert processing_changes == 1
    tree = ast.dump(parsed, include_attributes=False)
    expected = DIAGNOSTIC_AST if name == "phone_diagnostics.py" else SOURCE_AST[name]
    assert hashlib.sha256(tree.encode()).hexdigest() == expected


def test_wire_codec_is_identical_to_paired_addon_release():
    assert hashlib.sha256((ROOT / "learning_bridge_protocol.py").read_bytes()).hexdigest() == (
        "0c893356c519c83a7a0fb341cf4ecc7e572afc45d620530b28d2e6a0faf7bd4b"
    )


def test_native_learning_dependencies_remain_optional_and_declared():
    manifest = json.loads((ROOT.parent / "manifest.json").read_text())
    assert {"assist_pipeline", "http", "frontend", "panel_custom", "stt", "websocket_api"} <= set(
        manifest["after_dependencies"]
    )
    # Fixing import declarations must not require voice/frontend setup for Codex.
    assert not manifest.get("dependencies")
