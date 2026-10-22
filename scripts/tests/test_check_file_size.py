"""The file-size check fails over the cap and warns as a file nears it (#133)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_file_size


def _file(root: Path, name: str, lines: int) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n" * lines, encoding="utf-8")
    return path


def _run(root: Path, *extra: str) -> int:
    return check_file_size.main(["--root", str(root), "--no-git", *extra])


def test_a_file_near_the_cap_warns_without_failing(tmp_path, capsys):
    _file(tmp_path, "near.py", 285)
    _file(tmp_path, "small.py", 100)

    assert _run(tmp_path) == 0

    out = capsys.readouterr().out
    assert "WARNING: 1 file(s) at 280+ of 300 lines" in out
    assert "285  near.py" in out
    assert "small.py" not in out
    assert "OK: no files exceed 300 lines." in out


def test_the_warning_band_includes_both_ends(tmp_path):
    for lines in (279, 280, 300, 301):
        _file(tmp_path, f"f{lines}.ts", lines)

    near = check_file_size.find_near_cap(
        tmp_path.iterdir(), warn_lines=280, max_lines=300, exemptions=(), root=tmp_path
    )

    assert sorted(n for _, n in near) == [280, 300]


def test_over_the_cap_still_fails_and_is_not_also_a_warning(tmp_path, capsys):
    _file(tmp_path, "big.tsx", 301)

    assert _run(tmp_path) == 1

    out = capsys.readouterr().out
    assert "FAIL: 1 file(s) exceed 300 lines:" in out
    assert "WARNING" not in out


def test_no_warning_when_nothing_is_near(tmp_path, capsys):
    _file(tmp_path, "small.py", 10)

    assert _run(tmp_path) == 0
    assert "WARNING" not in capsys.readouterr().out


def test_the_threshold_is_configurable(tmp_path, capsys):
    _file(tmp_path, "mid.py", 150)

    assert _run(tmp_path, "--warn", "150") == 0
    assert "150  mid.py" in capsys.readouterr().out


def test_exempt_and_uncovered_files_are_not_warned_about(tmp_path, capsys):
    _file(tmp_path, "host/migrations/versions/0001_init.py", 290)
    _file(tmp_path, "notes.md", 290)

    assert _run(tmp_path) == 0
    assert "WARNING" not in capsys.readouterr().out
