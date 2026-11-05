"""Read-only source/package projection checks; no installation or publication."""

import argparse
import hashlib
import json
import tomllib
from pathlib import Path

DOMAIN = "codex_assist"
REPOSITORY = "https://github.com/DaFern/ha-codex-multi-assist"
REQUIRED = {
    "__init__.py",
    "manifest.json",
    "config_flow.py",
    "agent_profiles.py",
    "codex_auth.py",
    "codex_client.py",
    "codex_entry.py",
    "codex_image.py",
    "codex_models.py",
    "codex_protocol.py",
    "codex_runtime.py",
    "condition.py",
    "diagnostics.py",
    "error_formatting.py",
    "model_discovery.py",
    "schema_compat.py",
    "speaker_automation.py",
    "speaker_handoff.py",
    "speaker_packet.py",
    "stt.py",
    "trigger.py",
    "voice_match.py",
    "voice_match_stt.py",
    "entry_modules.py",
    "conversation.py",
    "ai_task.py",
    "repairs.py",
    "strings.json",
    "translations/en.json",
    "brand/icon.png",
    "triggers.yaml",
    "conditions.yaml",
    "learning/__init__.py",
    "learning/lifecycle.py",
    "learning/config_flow.py",
    "learning/const.py",
    "learning/phone_diagnostics.py",
    "learning/bridge_client.py",
    "learning/learning_bridge_protocol.py",
    "learning/coordinator.py",
    "learning/phone_flow.py",
    "learning/phone_runtime.py",
    "learning/phone_handoff.py",
    "learning/stt.py",
    "learning/conversation.py",
    "learning/launcher.py",
    "learning/readiness.py",
    "learning/discovery.py",
    "learning/health_issues.py",
    "learning/websocket_api.py",
    "learning/frontend/launch-panel.js",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def allowed_file(path):
    """Include runtime sources/assets only, not data, logs, credentials or caches."""
    if len(path.parts) == 1:
        return path.suffix == ".py" or path.name in {
            "manifest.json",
            "strings.json",
            "triggers.yaml",
            "conditions.yaml",
        }
    if len(path.parts) == 2:
        return (
            path.parts[0] == "learning"
            and path.suffix == ".py"
            or path.parts[0] == "translations"
            and path.suffix == ".json"
            or path.parts[0] == "brand"
            and path.suffix == ".png"
        )
    return path.as_posix() == "learning/frontend/launch-panel.js"


def package_projection(root):
    """Return would-be custom_components paths/bytes without creating an archive."""
    components = root / "custom_components"
    require(not components.is_symlink(), "custom_components must not be a symlink")
    domains = sorted(
        path.name for path in components.iterdir() if path.is_dir() and path.name != "__pycache__"
    )
    require(domains == [DOMAIN], "HACS requires exactly one integration: codex_assist")
    integration = components / DOMAIN
    require(not integration.is_symlink(), "Integration must not be a symlink")
    files = {}
    for path in sorted(integration.rglob("*")):
        relative = path.relative_to(integration)
        if "__pycache__" in relative.parts:
            continue
        require(not path.is_symlink(), "Runtime symlinks are not distributable")
        if path.is_dir():
            continue
        require(allowed_file(relative), "Unexpected runtime file; review package boundary")
        files[relative.as_posix()] = path.read_bytes()
    require(REQUIRED <= files.keys(), "Required runtime file/asset missing")
    require(all(files.values()), "Empty runtime source/asset")
    return {f"custom_components/{DOMAIN}/{name}": data for name, data in files.items()}


def check_distribution(root):
    # Reject runtime symlinks/unexpected files before reading even the manifest.
    files = package_projection(root)
    hacs = json.loads((root / "hacs.json").read_text())
    manifest = json.loads((root / f"custom_components/{DOMAIN}/manifest.json").read_text())
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    lock = tomllib.loads((root / "uv.lock").read_text())
    local = [package for package in lock["package"] if package["name"] == project["name"]]
    require(len(local) == 1, "Expected exactly one local project in lockfile")
    require(
        manifest["version"] == project["version"] == local[0]["version"],
        "Manifest/project/lockfile versions differ",
    )
    require(
        manifest["domain"] == DOMAIN and manifest["config_flow"] is True,
        "Unexpected integration identity/config flow",
    )
    require(
        manifest["documentation"] == REPOSITORY
        and manifest["issue_tracker"] == REPOSITORY + "/issues",
        "Manifest must identify this fork",
    )
    require(
        hacs["content_in_root"] is False and not hacs.get("zip_release", False),
        "HACS must use the repository integration directory, not a release ZIP",
    )
    require(hacs["homeassistant"] == "2026.6.0", "Preserve the Codex-only HA floor")
    prefix = f"custom_components/{DOMAIN}/"
    require(
        json.loads(files[prefix + "strings.json"])
        == json.loads(files[prefix + "translations/en.json"]),
        "English translation and strings differ",
    )
    digest = hashlib.sha256()
    for name, data in files.items():
        digest.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
    return {
        "version": manifest["version"],
        "domain": DOMAIN,
        "files": len(files),
        "projection_sha256": digest.hexdigest(),
        "installed_or_published": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = check_distribution(args.root)
    except (ValueError, OSError, KeyError) as err:
        parser.exit(1, f"Distribution check failed: {err}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
