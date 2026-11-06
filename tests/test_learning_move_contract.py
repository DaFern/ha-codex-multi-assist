"""Pin safety-critical moved logic to the reviewed 0.4.5 companion, not a sibling checkout."""

import ast
import hashlib
import json
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


@pytest.mark.parametrize("name", SOURCE_AST)
def test_safety_logic_matches_reviewed_source(name):
    tree = ast.dump(ast.parse((ROOT / name).read_text()), include_attributes=False)
    expected = DIAGNOSTIC_AST if name == "phone_diagnostics.py" else SOURCE_AST[name]
    assert hashlib.sha256(tree.encode()).hexdigest() == expected


def test_wire_codec_is_identical_to_paired_addon_release():
    assert hashlib.sha256((ROOT / "learning_bridge_protocol.py").read_bytes()).hexdigest() == (
        "0c893356c519c83a7a0fb341cf4ecc7e572afc45d620530b28d2e6a0faf7bd4b"
    )


def test_native_learning_dependencies_remain_optional_and_declared():
    manifest = json.loads((ROOT.parent / "manifest.json").read_text())
    assert {
        "assist_pipeline", "http", "frontend", "panel_custom", "stt", "websocket_api"
    } <= set(manifest["after_dependencies"])
    # Fixing import declarations must not require voice/frontend setup for Codex.
    assert not manifest.get("dependencies")
