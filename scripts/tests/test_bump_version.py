"""The repo-local bump script must never rewrite framework dependency pins.

The framework repo's version of this script rewrites every ``simple_module_*``
requirement to ``==<version>``. Run here, that would turn
``simple_module_core>=0.0.35,<0.1`` into ``==<this repo's version>`` — pinning
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


def _all_manifests() -> list:
    """Every file a bump rewrites — discovered the same way the script does.

    Listing them individually is what let this test corrupt the tree: it was
    written when pagebuilder was the only module, so a bump left every *other*
    module's manifest sitting at the test's throwaway version, and the very
    next `--check-current` run failed on a tree nobody had edited.
    """
    return [
        REPO / "pyproject.toml",
        *sorted((REPO / "modules").glob("*/pyproject.toml")),
        *sorted((REPO / "modules").glob("*/package.json")),
    ]


def test_framework_pins_survive_a_real_bump():
    """Round-trip a real bump and restore, asserting the pins are unchanged."""
    manifest = REPO / "modules" / "pagebuilder" / "pyproject.toml"
    snapshot = {path: path.read_text() for path in _all_manifests()}
    try:
        assert _run("9.9.9").returncode == 0
        bumped = tomlkit.parse(manifest.read_text())
        assert str(bumped["project"]["version"]) == "9.9.9"
        deps = [str(d) for d in bumped["project"]["dependencies"]]
        assert "simple_module_core>=0.0.35,<0.1" in deps
        assert not any("simple_module_core==" in d for d in deps)
    finally:
        for path, original in snapshot.items():
            path.write_text(original)


def test_a_real_bump_restores_every_module_not_just_the_first():
    """Guards the fixture above: after the round-trip the tree must be synced.

    Without it, a second module's manifest silently keeps the bumped version.
    """
    test_framework_pins_survive_a_real_bump()
    assert _run("--check-current").returncode == 0
