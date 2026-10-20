"""The migration-heads check fails on a split history and passes on one head."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_migration_heads


def _revision(versions: Path, rev: str, down: str | tuple[str, ...] | None) -> None:
    versions.mkdir(parents=True, exist_ok=True)
    (versions / f"{rev}_r.py").write_text(
        f"revision = {rev!r}\ndown_revision = {down!r}\nbranch_labels = None\ndepends_on = None\n"
        "def upgrade():\n    pass\ndef downgrade():\n    pass\n",
        encoding="utf-8",
    )


def test_two_heads_fail(tmp_path, capsys):
    versions = tmp_path / "versions"
    _revision(versions, "base", None)
    _revision(versions, "left", "base")
    _revision(versions, "right", "base")
    assert check_migration_heads.main(["--migrations", str(tmp_path)]) == 1
    assert "found 2: left, right" in capsys.readouterr().out


def test_merged_history_passes(tmp_path):
    versions = tmp_path / "versions"
    _revision(versions, "base", None)
    _revision(versions, "left", "base")
    _revision(versions, "right", "base")
    _revision(versions, "merge", ("left", "right"))
    assert check_migration_heads.main(["--migrations", str(tmp_path)]) == 0


def test_host_history_has_one_head():
    assert len(check_migration_heads.heads(check_migration_heads.MIGRATIONS)) == 1
