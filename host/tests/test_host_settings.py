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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from simple_module_core.dotenv import parse_dotenv

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


@pytest.fixture(scope="module")
def _template_db(tmp_path_factory):
    """A migrated database holding ``host.rate_limit_public = 2/minute``.

    Built once: the two alembic runs dominate the module's time, and each test
    boots its own app against a private copy, so what one writes stays out of
    the other.
    """
    path = tmp_path_factory.mktemp("host-settings") / "template.db"
    url = f"sqlite+aiosqlite:///{path}"
    _run(["-m", "alembic", "-c", "host/alembic.ini", "upgrade", "heads"], url)
    _run(["scripts/set_setting.py", "host", "rate_limit_public", "2/minute"], url)
    return path


@pytest.fixture
def stored_limit(_template_db, tmp_path, monkeypatch):
    """A private copy of the template database, selected through the environment."""
    copy = tmp_path / "host.db"
    shutil.copyfile(_template_db, copy)
    url = f"sqlite+aiosqlite:///{copy}"
    monkeypatch.setenv("SM_DATABASE_URL", url)
    monkeypatch.delenv("SM_RATE_LIMIT_PUBLIC", raising=False)
    # ``.env`` counts as the environment and would win over the stored row.
    if "SM_RATE_LIMIT_PUBLIC" in parse_dotenv():
        pytest.skip("the repo's .env sets SM_RATE_LIMIT_PUBLIC")
    return url


def _boot_main():
    """Import ``main`` afresh: what a restart of the host does."""
    sys.modules.pop("main", None)
    return importlib.import_module("main").app


def _statuses(app, n: int) -> list[int]:
    """``n`` anonymous GETs of the public page, one request each.

    Redirects are not followed: a fresh database sends the login page to the
    setup wizard (302 → ``/setup``), itself public, so following it would
    spend two of the same client's ``rate_limit_public`` slots per GET.
    """
    with TestClient(app, follow_redirects=False) as client:
        return [client.get(PUBLIC_PAGE).status_code for _ in range(n)]


@pytest.fixture(autouse=True)
def _forget_main():
    yield
    sys.modules.pop("main", None)


def test_stored_rate_limit_takes_effect_after_restart(stored_limit):
    app = _boot_main()
    assert app.state.sm.settings.rate_limit_public == "2/minute"
    statuses = _statuses(app, 4)
    # Exactly two admitted, then the limit; the default, 120/minute, would
    # admit all four.
    assert 429 not in statuses[:2], statuses
    assert statuses[2:] == [429, 429], statuses


def test_environment_wins_over_the_stored_value(stored_limit, monkeypatch):
    """The framework's precedence: env, then database, then default."""
    monkeypatch.setenv("SM_RATE_LIMIT_PUBLIC", "1000/minute")
    app = _boot_main()
    assert app.state.sm.settings.rate_limit_public == "1000/minute"
    assert 429 not in _statuses(app, 4)
