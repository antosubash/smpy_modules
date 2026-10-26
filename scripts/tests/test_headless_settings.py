"""Headless scripts never create the deployment's session key (#260 follow-up).

``merge_host_settings`` generates and commits a ``host.secret_key`` row when
neither the environment nor the database has one. ``set_setting.py`` and
``seed_usage.py`` build their settings through ``headless_settings``, which
refuses in that state instead, and otherwise reuses the key without writing.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from headless_settings import NO_KEY_MESSAGE, headless_settings  # noqa: E402
from simple_module_hosting._secret_key import ensure_secret_key  # noqa: E402
from simple_module_hosting.bootstrap_settings import BootstrapSettings  # noqa: E402

KEY_ROW = "host.secret_key"


def _env(url: str, project_root: Path) -> dict[str, str]:
    """The environment without any secret: no SM_SECRET_KEY and no ``.env``.

    ``SM_PROJECT_ROOT`` points the ``.env`` lookup at an empty directory, so
    the repo's own ``.env`` (which carries a key) is not read.
    """
    env = {k: v for k, v in os.environ.items() if k != "SM_SECRET_KEY"}
    return {**env, "SM_DATABASE_URL": url, "SM_PROJECT_ROOT": str(project_root)}


@pytest.fixture(scope="module")
def _migrated(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("headless") / "template.db"
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


@pytest.fixture
def db(_migrated, tmp_path, monkeypatch) -> Path:
    """A private copy of the migrated database, with no key row, and no env key."""
    copy = tmp_path / "host.db"
    copy.write_bytes(_migrated.read_bytes())
    monkeypatch.delenv("SM_SECRET_KEY", raising=False)
    return copy


def _url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path}"


def _bootstrap(path: Path) -> BootstrapSettings:
    # ``_env_file=None``: the repo's ``.env`` must not supply a key here.
    return BootstrapSettings(_env_file=None, database_url=_url(path))


def _key_rows(path: Path) -> list[str]:
    with sqlite3.connect(path) as conn:
        return [
            r[0]
            for r in conn.execute("SELECT value FROM settings_setting WHERE key = ?", (KEY_ROW,))
        ]


def test_set_setting_refuses_without_a_key_and_writes_nothing(db, tmp_path):
    empty_root = tmp_path / "root"
    empty_root.mkdir()
    result = subprocess.run(
        [sys.executable, "scripts/set_setting.py", "host", "rate_limit_public", "5/minute"],
        cwd=REPO,
        env=_env(_url(db), empty_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert NO_KEY_MESSAGE in result.stderr
    assert _key_rows(db) == []


def test_refuses_without_a_key(db):
    with pytest.raises(SystemExit, match="no secret key provisioned"):
        headless_settings(_bootstrap(db))
    assert _key_rows(db) == []


def test_an_environment_key_is_used_and_nothing_is_written(db, monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", "from-the-environment")
    settings = headless_settings(_bootstrap(db))
    assert settings.secret_key == "from-the-environment"
    assert _key_rows(db) == []


def test_a_stored_key_is_reused_and_nothing_new_is_written(db):
    # What the app's first boot without SM_SECRET_KEY does.
    stored = ensure_secret_key(_url(db))
    assert _key_rows(db) == [stored]
    settings = headless_settings(_bootstrap(db))
    assert settings.secret_key == stored
    assert _key_rows(db) == [stored]
