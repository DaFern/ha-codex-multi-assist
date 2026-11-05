"""Run the add-on's encrypted bridge/phone tests against this integration's client.

Usage: python scripts/check_learning_addon_contract.py /path/to/wyoming-voice-match-ha
Requires the add-on's isolated test dependencies. Aliases exist only in this test
process; no compatibility aliases or source rewrites ship in the integration.
"""

import argparse
import importlib
import sys
import unittest
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("addon_checkout", type=Path)
    args = parser.parse_args()
    addon = args.addon_checkout.resolve()
    root = Path(__file__).resolve().parents[1]
    if not (addon / "tests/test_learning_bridge.py").is_file():
        parser.error("Expected the Wyoming Voice Match source checkout")
    sys.path[:0] = [str(root), str(addon), str(addon / "tests")]
    components = importlib.import_module("custom_components")
    components.__path__.append(str(addon / "custom_components"))
    # Load the historical parent only to satisfy Python's import hierarchy. The
    # tests' imports of every exercised client/controller module resolve to the
    # new integration, while the server/voice-store fixtures remain the add-on's.
    importlib.import_module("custom_components.voice_match_enrollment")
    for name in ("learning_bridge_protocol", "bridge_client", "coordinator", "phone_flow"):
        module = importlib.import_module(f"custom_components.codex_assist.learning.{name}")
        sys.modules[f"custom_components.voice_match_enrollment.{name}"] = module
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        ["test_learning_bridge", "test_phone_learning"]
    )
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    # Missing dependencies must not turn a skipped encrypted round-trip into a
    # purported pass. The server's DSP stays synthetic; no hardware is exercised.
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == "__main__":
    sys.exit(main())
