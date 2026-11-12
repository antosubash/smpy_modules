"""Fixtures shared by the script tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def _migrated(tmp_path_factory) -> Path:
    """The host's migrated SQLite database, built once per test module; copy it."""
    path = tmp_path_factory.mktemp("migrated") / "template.db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "host/alembic.ini", "upgrade", "heads"],
        cwd=REPO,
        env={**os.environ, "SM_DATABASE_URL": f"sqlite+aiosqlite:///{path}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return path
