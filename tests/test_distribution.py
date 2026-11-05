"""Packaging metadata/assets and fork install identity, without HA or network."""

import json
import re
import shutil
from pathlib import Path

import pytest

from scripts.check_distribution import check_distribution, package_projection

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "custom_components/codex_assist"


@pytest.fixture
def candidate(tmp_path):
    for name in ("hacs.json", "pyproject.toml", "uv.lock"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    shutil.copytree(
        ROOT / PACKAGE, tmp_path / PACKAGE, ignore=shutil.ignore_patterns("__pycache__")
    )
    return tmp_path


def test_distribution_has_one_complete_runtime_and_no_generated_data():
    result = check_distribution(ROOT)
    assert result["installed_or_published"] is False
    files = package_projection(ROOT)
    assert all(name.startswith(PACKAGE + "/") for name in files)
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in files)
    assert result == check_distribution(ROOT)


@pytest.mark.parametrize(
    "missing",
    [
        "learning/frontend/launch-panel.js",
        "learning/learning_bridge_protocol.py",
        "repairs.py",
        "translations/en.json",
        "brand/icon.png",
        "triggers.yaml",
    ],
)
def test_distribution_refuses_missing_required_runtime_asset(candidate, missing):
    (candidate / PACKAGE / missing).unlink()
    with pytest.raises(ValueError, match="missing"):
        check_distribution(candidate)


def test_distribution_refuses_two_domains(candidate):
    (candidate / "custom_components/voice_match_enrollment").mkdir()
    with pytest.raises(ValueError, match="exactly one integration"):
        check_distribution(candidate)


@pytest.mark.parametrize("metadata", ["pyproject.toml", "uv.lock"])
def test_distribution_refuses_version_drift(candidate, metadata):
    path = candidate / metadata
    version = json.loads((candidate / PACKAGE / "manifest.json").read_text())["version"]
    path.write_text(path.read_text().replace(f'version = "{version}"', 'version = "0.0.1"'))
    with pytest.raises(ValueError, match="versions differ"):
        check_distribution(candidate)


def test_distribution_refuses_external_symlink(candidate, tmp_path):
    target = tmp_path / "synthetic.py"
    target.write_text("# not runtime code\n")
    (candidate / PACKAGE / "linked.py").symlink_to(target)
    with pytest.raises(ValueError, match="symlinks"):
        check_distribution(candidate)


def test_distribution_refuses_symlinked_manifest_before_reading_it(candidate):
    path = candidate / PACKAGE / "manifest.json"
    path.unlink()
    # Invalid JSON ensures the symlink check must happen before parsing its target.
    target = candidate / "synthetic-target.json"
    target.write_text("not JSON")
    path.symlink_to(target)
    with pytest.raises(ValueError, match="symlinks"):
        check_distribution(candidate)


@pytest.mark.parametrize(
    "name",
    [
        "learning/recording.wav",
        "learning/learning_bridge.json",
        "secrets.yaml",
        ".env",
        "debug.log",
    ],
)
def test_distribution_refuses_unexpected_data_without_packaging_it(candidate, name):
    (candidate / PACKAGE / name).write_text("synthetic non-runtime data")
    with pytest.raises(ValueError, match="Unexpected runtime file"):
        check_distribution(candidate)


def test_distribution_refuses_upstream_manifest_identity(candidate):
    path = candidate / PACKAGE / "manifest.json"
    data = json.loads(path.read_text())
    data["documentation"] = "https://github.com/itsreverence/ha-codex-assist"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="this fork"):
        check_distribution(candidate)


def test_distribution_ignores_local_bytecode_without_removing_it(candidate):
    cache = candidate / PACKAGE / "learning/__pycache__"
    cache.mkdir()
    bytecode = cache / "synthetic.pyc"
    bytecode.write_bytes(b"synthetic bytecode")
    assert check_distribution(candidate) == check_distribution(ROOT)
    assert bytecode.exists()


def test_fork_install_links_are_not_upstream_downloads_or_default_catalog_claims():
    readme = (ROOT / "README.md").read_text()
    assert "owner=DaFern&repository=ha-codex-multi-assist&category=integration" in readme
    assert "owner=itsreverence" not in readme
    assert "HACS-Default" not in readme
    assert "Codex Assist is in the HACS default catalog" not in readme
    assert "docs/INSTALLATION.md" in readme and "docs/BETA_ACCEPTANCE.md" in readme
    assert (
        "https://github.com/DaFern/ha-codex-multi-assist/issues"
        in (ROOT / "SUPPORT.md").read_text()
    )


@pytest.mark.parametrize(
    "name",
    [
        "README.md",
        "SUPPORT.md",
        "docs/INSTALLATION.md",
        "docs/BETA_ACCEPTANCE.md",
        "docs/COMBINED_INTEGRATION.md",
        "docs/RELEASING.md",
        "docs/TESTING.md",
    ],
)
def test_distribution_guides_local_link_targets_exist(name):
    path = ROOT / name
    for target in re.findall(r"\]\(([^ )]+)\)", path.read_text()):
        if "://" in target or target.startswith("#"):
            continue
        assert (path.parent / target.split("#", 1)[0]).is_file(), (name, target)
