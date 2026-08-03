"""The repo-local bump script must never rewrite framework dependency pins.

The framework repo's version of this script rewrites every ``simple_module_*``
requirement to ``==<version>``. Run here, that would turn
``simple_module_core>=0.0.25,<0.1`` into ``==<this repo's version>`` — pinning
the framework to a version that does not exist. These tests are the guard.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import tomlkit

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "bump_version.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )


def test_dry_run_lists_root_and_module_manifests():
    result = _run("9.9.9", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "modules/pagebuilder/pyproject.toml" in result.stdout
    assert "modules/pagebuilder/package.json" in result.stdout


def test_framework_pins_are_never_rewritten():
    """A dry run must not claim it would touch any framework requirement."""
    result = _run("9.9.9", "--dry-run")
    assert result.returncode == 0, result.stderr
    for dist in ("simple_module_core", "simple_module_db", "simple_module_hosting"):
        assert dist not in result.stdout


def test_dry_run_leaves_the_tree_untouched():
    before = (REPO / "modules" / "pagebuilder" / "pyproject.toml").read_text()
    _run("9.9.9", "--dry-run")
    assert (REPO / "modules" / "pagebuilder" / "pyproject.toml").read_text() == before


def test_check_current_passes_on_a_synced_tree():
    result = _run("--check-current")
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_fails_on_a_version_the_tree_does_not_have():
    assert _run("--check", "9.9.9").returncode != 0


def test_rejects_a_malformed_version():
    assert _run("not-a-version").returncode == 2


def test_module_version_matches_root_version():
    root = tomlkit.parse((REPO / "pyproject.toml").read_text())["project"]["version"]
    mod = tomlkit.parse((REPO / "modules" / "pagebuilder" / "pyproject.toml").read_text())[
        "project"
    ]["version"]
    assert str(root) == str(mod)


def test_framework_pins_survive_a_real_bump():
    """Round-trip a real bump and restore, asserting the pins are unchanged."""
    manifest = REPO / "modules" / "pagebuilder" / "pyproject.toml"
    original = manifest.read_text()
    root_manifest = REPO / "pyproject.toml"
    root_original = root_manifest.read_text()
    package_json = REPO / "modules" / "pagebuilder" / "package.json"
    package_original = package_json.read_text()
    try:
        assert _run("9.9.9").returncode == 0
        bumped = tomlkit.parse(manifest.read_text())
        assert str(bumped["project"]["version"]) == "9.9.9"
        deps = [str(d) for d in bumped["project"]["dependencies"]]
        assert "simple_module_core>=0.0.25,<0.1" in deps
        assert not any("simple_module_core==" in d for d in deps)
    finally:
        manifest.write_text(original)
        root_manifest.write_text(root_original)
        package_json.write_text(package_original)
