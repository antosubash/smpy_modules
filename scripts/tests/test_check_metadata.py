"""The root pytest `testpaths` must name exactly the module directories (#118)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_metadata

REPO = Path(__file__).resolve().parents[2]


def _repo(tmp_path: Path, modules: list[str], testpaths: list[str]) -> Path:
    for name in modules:
        (tmp_path / "modules" / name / "tests").mkdir(parents=True)
        (tmp_path / "modules" / name / "pyproject.toml").write_text("", encoding="utf-8")
    for fixed in check_metadata.NON_MODULE_TESTPATHS:
        (tmp_path / fixed).mkdir(parents=True, exist_ok=True)
    listed = ", ".join(f'"{p}"' for p in testpaths)
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.pytest.ini_options]\ntestpaths = [{listed}]\n", encoding="utf-8"
    )
    return tmp_path


def test_matching_testpaths_pass(tmp_path):
    root = _repo(
        tmp_path, ["a", "b"], ["host/tests", "modules/a/tests", "modules/b/tests", "scripts/tests"]
    )
    assert check_metadata.check_testpaths(root) == []


def test_module_missing_from_testpaths_fails(tmp_path):
    root = _repo(tmp_path, ["a", "b"], ["host/tests", "modules/a/tests", "scripts/tests"])
    errors = check_metadata.check_testpaths(root)
    assert len(errors) == 1
    assert "modules/b/tests" in errors[0]
    assert "missing" in errors[0]


def test_testpath_without_a_module_fails(tmp_path):
    root = _repo(
        tmp_path, ["a"], ["host/tests", "modules/a/tests", "modules/gone/tests", "scripts/tests"]
    )
    errors = check_metadata.check_testpaths(root)
    assert len(errors) == 1
    assert "modules/gone/tests" in errors[0]


def test_missing_host_or_scripts_testpath_fails(tmp_path):
    root = _repo(tmp_path, ["a"], ["modules/a/tests"])
    errors = "\n".join(check_metadata.check_testpaths(root))
    assert "missing 'host/tests'" in errors
    assert "missing 'scripts/tests'" in errors


def test_main_reports_testpath_drift(tmp_path, capsys):
    root = _repo(tmp_path, ["a"], ["host/tests", "scripts/tests"])
    assert check_metadata.main(["--root", str(root)]) == 1
    assert "modules/a/tests" in capsys.readouterr().err


def test_repo_testpaths_match_modules():
    assert check_metadata.check_testpaths(REPO) == []
