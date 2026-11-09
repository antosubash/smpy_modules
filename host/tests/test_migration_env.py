"""``env.py`` ignores SQLite's false index change, and nothing beyond it.

``tenant_browse`` mixes columns with ``created_at DESC``, which SQLite reflects as
a plain column. ``alembic check`` must stay quiet about that, but still see the
index on other columns. A *missing* expression index is out of reach here: Alembic
skips those on SQLite itself, and the Postgres ``alembic check`` in CI catches it.
Real alembic against a real file.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INDEX = "ix_file_storage_stored_file_tenant_browse"
TABLE = "file_storage_stored_file"


def _alembic(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "host/alembic.ini", *args],
        cwd=REPO,
        env={**os.environ, "SM_DATABASE_URL": f"sqlite+aiosqlite:///{path}"},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def migrated(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("env") / "check.db"
    done = _alembic(path, "upgrade", "heads")
    assert done.returncode == 0, done.stderr[-2000:]
    return path


def test_the_migrated_index_is_not_a_change(migrated) -> None:
    done = _alembic(migrated, "check")
    assert done.returncode == 0, done.stderr[-2000:]


def test_an_index_on_other_columns_is_still_reported(migrated, tmp_path) -> None:
    copy = tmp_path / "wrong-columns.db"
    copy.write_bytes(migrated.read_bytes())
    with sqlite3.connect(copy) as db:
        db.execute(f"DROP INDEX {INDEX}")
        db.execute(f"CREATE INDEX {INDEX} ON {TABLE} (tenant_id)")
    done = _alembic(copy, "check")
    assert done.returncode != 0
    assert INDEX in done.stdout + done.stderr
