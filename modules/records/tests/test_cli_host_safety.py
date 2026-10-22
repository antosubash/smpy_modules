"""``--app``'s edges (GH #157): the database check, and leaving the lifespan.

Split from ``test_cli_host`` for the 300-line cap. Asserted: ``--database-url``
is compared as a database, not as text, so a relative SQLite path, another
query order or another escaping restates the app's URL; a refusal never prints
a password; and :func:`sm_records.cli_host.host_bus` leaves the lifespan the
normal way whatever ends the block — an error, a cancellation, Ctrl-C — and
disposes the engine when startup itself fails.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from sm_records.cli_host import host_bus, resolve_database_url


def _app(database_url: str = "sqlite+aiosqlite:///:memory:", *, fail_startup: bool = False):
    phase: list[str] = []
    disposed: list[bool] = []

    async def dispose() -> None:
        disposed.append(True)

    @asynccontextmanager
    async def lifespan(app):
        phase.append("up")
        if fail_startup:
            raise RuntimeError("a module's on_startup failed")
        yield
        phase.append("down")

    app = FastAPI(lifespan=lifespan)
    app.state.sm = SimpleNamespace(
        event_bus=object(),
        db=SimpleNamespace(engine=SimpleNamespace(dispose=dispose)),
        settings=SimpleNamespace(database_url=database_url),
    )
    return app, phase, disposed


def _never() -> Any:
    raise AssertionError("the default is not consulted when --app is given")


@pytest.fixture
def project_root(tmp_path, monkeypatch):
    """Anchor relative SQLite paths at ``tmp_path``, as the framework would."""
    monkeypatch.setenv("SM_PROJECT_ROOT", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize(
    ("app_url", "given"),
    [
        # The framework absolutises a relative SQLite path under the project root.
        ("sqlite+aiosqlite:///{root}/host/app.db", "sqlite+aiosqlite:///./host/app.db"),
        ("sqlite+aiosqlite:///{root}/host/app.db", "sqlite+aiosqlite:///host/../host/app.db"),
        (
            "postgresql+asyncpg://u:p%40ss@db:5432/app?ssl=require&timeout=5",
            "postgresql+asyncpg://u:p%40ss@db:5432/app?timeout=5&ssl=require",
        ),
        # One password, escaped or not where the escape is optional.
        ("postgresql+asyncpg://u:p-ss@db/app", "postgresql+asyncpg://u:p%2Dss@db/app"),
    ],
)
def test_a_database_url_that_restates_the_apps_is_accepted(project_root, app_url, given):
    app, _, _ = _app(app_url.format(root=project_root))

    assert resolve_database_url(app, given, _never) == app.state.sm.settings.database_url


def test_a_conflicting_database_url_is_refused_without_printing_passwords(project_root):
    app, _, _ = _app("postgresql+asyncpg://admin:app-secret@db/app")

    with pytest.raises(SystemExit) as refused:
        resolve_database_url(app, "postgresql+asyncpg://admin:other-secret@db/other", _never)

    message = str(refused.value)
    assert "is not the database --app writes to" in message
    assert "app-secret" not in message
    assert "other-secret" not in message
    assert "***" in message


def test_a_database_url_that_is_not_one_is_refused_without_echoing_it(project_root):
    app, _, _ = _app()

    with pytest.raises(SystemExit, match="is not a database URL") as refused:
        resolve_database_url(app, "not a url :secret", _never)

    assert "secret" not in str(refused.value)


@pytest.mark.parametrize(
    "failure", [RuntimeError("boom"), SystemExit(1), asyncio.CancelledError(), KeyboardInterrupt()]
)
def test_whatever_ends_the_block_the_lifespan_is_left_normally(failure):
    app, phase, _ = _app()

    async def run() -> None:
        async with host_bus(app, "seed") as bus:
            assert bus is app.state.sm.event_bus
            raise failure

    with pytest.raises(type(failure)):
        asyncio.run(run())

    assert phase == ["up", "down"]


def test_the_original_failure_wins_over_a_failing_shutdown():
    @asynccontextmanager
    async def lifespan(app):
        yield
        raise RuntimeError("shutdown failed")

    app = FastAPI(lifespan=lifespan)
    app.state.sm = SimpleNamespace(event_bus=object())

    async def run() -> None:
        async with host_bus(app, "seed"):
            raise ValueError("the write failed")

    with pytest.raises(ValueError, match="the write failed"):
        asyncio.run(run())


def test_a_startup_that_fails_disposes_the_engine_and_reraises():
    app, phase, disposed = _app(fail_startup=True)

    async def run() -> None:
        async with host_bus(app, "seed"):
            raise AssertionError("the block never runs when startup fails")

    with pytest.raises(RuntimeError, match="on_startup failed"):
        asyncio.run(run())

    assert phase == ["up"]
    assert disposed == [True]
