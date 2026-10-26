"""Host settings stored in the database reach the demo host's own app (#260).

``host/main.py`` used to build the app from ``Settings()``, which reads the
environment only, so a ``host.*`` row written on the Settings screen or with
``scripts/set_setting.py`` was stored and never read. It now builds them with
the framework's ``merge_host_settings``: env, then the database, then the
defaults. These tests write ``rate_limit_public`` the way an operator would,
rebuild ``main:app`` (a restart), and count 429s on an anonymous public page.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "host"))

# What ``main.py`` imports before ``create_app`` (see test_host_boots.py).
import records_collections  # noqa: E402, F401

# A public page every anonymous visitor reaches, so ``rate_limit_public``
# applies to it.
PUBLIC_PAGE = "/users/login"


def _run(args: list[str], url: str) -> None:
    result = subprocess.run(
        [sys.executable, *args],
        cwd=REPO,
        env={**os.environ, "SM_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]


@pytest.fixture
def stored_limit(tmp_path, monkeypatch):
    """A migrated database holding ``host.rate_limit_public = 2/minute``."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'host.db'}"
    _run(["-m", "alembic", "-c", "host/alembic.ini", "upgrade", "heads"], url)
    _run(["scripts/set_setting.py", "host", "rate_limit_public", "2/minute"], url)
    monkeypatch.setenv("SM_DATABASE_URL", url)
    monkeypatch.delenv("SM_RATE_LIMIT_PUBLIC", raising=False)
    return url


def _boot_main():
    """Import ``main`` afresh: what a restart of the host does."""
    sys.modules.pop("main", None)
    return importlib.import_module("main").app


def _statuses(app, n: int) -> list[int]:
    with TestClient(app) as client:
        return [client.get(PUBLIC_PAGE).status_code for _ in range(n)]


@pytest.fixture(autouse=True)
def _forget_main():
    yield
    sys.modules.pop("main", None)


def test_stored_rate_limit_takes_effect_after_restart(stored_limit):
    app = _boot_main()
    assert app.state.sm.settings.rate_limit_public == "2/minute"
    statuses = _statuses(app, 4)
    assert statuses[0] == 200
    assert 429 in statuses  # the default, 120/minute, would admit all four


def test_environment_wins_over_the_stored_value(stored_limit, monkeypatch):
    """The framework's precedence: env, then database, then default."""
    monkeypatch.setenv("SM_RATE_LIMIT_PUBLIC", "1000/minute")
    app = _boot_main()
    assert app.state.sm.settings.rate_limit_public == "1000/minute"
    assert 429 not in _statuses(app, 4)
