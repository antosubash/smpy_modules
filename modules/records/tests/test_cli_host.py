"""``--app``: a standalone CLI write reaches the host's subscribers (GH #157).

Driven through :func:`sm_records.cli.main`, the way an operator runs it, with
a host written to ``tmp_path`` for the occasion: a FastAPI app whose lifespan
records when it is up and whose bus records what it heard, and in which phase.
Asserted: an applied import and a seed publish to that bus while the lifespan
is running, and the lifespan is left afterwards; a refused import publishes
nothing and still shuts the host down; a factory works in place of an app; a
write without ``--app`` warns on stderr and still writes; a dry run neither
starts a host nor warns; and an ``--app`` that is not one, or a
``--database-url`` that contradicts it, stops before anything is written.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import re
import sys
from typing import Any

import pytest
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sm_records.cli import main
from sm_records.contracts.events import RecordCreated
from sm_records.models import Base, Record, RecordType
from sqlalchemy import func, select

FIELDS = [{"key": "name", "type": "text", "label": "Name", "indexed": True}]

HOST = """
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from simple_module_core.events import EventBus
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sqlalchemy import event as sa_event
from sm_records.contracts import events

seen = []
phase = []
commits = []


def build():
    bus = EventBus()

    async def handle(event):
        seen.append((phase[-1], event))

    for name in events.__all__:
        bus.subscribe(getattr(events, name), handle)

    db = init_db(URL)
    register_listeners(db)
    # A listener only this app's sessions carry: a write through any other
    # engine (one the CLI opened itself) never reaches it.
    sa_event.listen(db.sync_session_class, "after_commit", lambda s: commits.append(phase[-1]))

    @asynccontextmanager
    async def lifespan(app):
        phase.append("up")
        yield
        await db.engine.dispose()
        phase.append("down")

    app = FastAPI(lifespan=lifespan)
    app.state.sm = SimpleNamespace(event_bus=bus, db=db, settings=SimpleNamespace(database_url=URL))
    return app


app = build()
not_an_app = object()
"""


async def _create_db(url: str) -> None:
    state = init_db(url)
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with state.session_factory() as session:
        session.add(RecordType(key="widget", label="W", label_plural="Ws", fields=FIELDS))
        await session.commit()
    await state.engine.dispose()


async def _count(url: str) -> int:
    state = init_db(url)
    try:
        async with state.session_factory() as session:
            return int((await session.execute(select(func.count(Record.id)))).scalar_one())
    finally:
        await state.engine.dispose()


@pytest.fixture
def url(tmp_path) -> str:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}"
    asyncio.run(_create_db(db_url))
    return db_url


@pytest.fixture
def host(tmp_path, url, monkeypatch, request) -> Any:
    """A host module in ``tmp_path``, importable through ``--app-dir``.

    Named per test so the import is fresh, and taken back out of
    ``sys.modules``/``sys.path`` afterwards so no other test can import it.
    """
    name = f"fake_host_{request.node.name}".replace("[", "_").replace("]", "_")
    (tmp_path / f"{name}.py").write_text(f"URL = {url!r}\n" + HOST)
    monkeypatch.setattr(sys, "path", list(sys.path))
    yield name, str(tmp_path)
    sys.modules.pop(name, None)


def _module(name: str) -> Any:
    return importlib.import_module(name)


def _file(tmp_path, rows: list[dict]) -> str:
    path = tmp_path / "in.json"
    path.write_text(json.dumps({"records": rows}))
    return str(path)


def _import(path: str, *extra: str) -> int:
    return main(["import", "--type", "widget", path, *extra])


def test_an_applied_import_publishes_to_the_hosts_bus_while_it_is_up(host, url, tmp_path, capsys):
    name, app_dir = host
    path = _file(tmp_path, [{"data": {"name": "A"}}, {"data": {"name": "B"}}])

    assert _import(path, "--apply", "--app", f"{name}:app", "--app-dir", app_dir) == 0

    mod = _module(name)
    assert [(when, type(event)) for when, event in mod.seen] == [("up", RecordCreated)] * 2
    assert mod.phase == ["up", "down"]
    # Written through the app's own database state, not a second engine.
    assert mod.commits == ["up"]
    assert "WARNING" not in capsys.readouterr().err


def test_a_seed_publishes_one_event_per_record_through_a_factory(host, url, capsys):
    name, app_dir = host

    seeded = ["seed", "--records", "12", "--seed", "3"]
    assert main([*seeded, "--app", f"{name}:build", "--app-dir", app_dir]) == 0

    mod = _module(name)
    created = [event for _, event in mod.seen if isinstance(event, RecordCreated)]
    # The seeder's own total, not a count of ``records_record``: once another
    # test has declared the ``events`` collection, ``event`` rows live elsewhere.
    out = capsys.readouterr().out
    total = int(re.search(r"records seed: (\d+) record\(s\) in tenant", out)[1])
    assert len(created) == total > 0
    assert {when for when, _ in mod.seen} == {"up"}
    assert mod.commits
    assert set(mod.commits) == {"up"}
    # Only the factory's app (the CLI's) started; the module-level one never did.
    assert mod.phase == ["up", "down"]


def test_a_refused_import_publishes_nothing_and_still_shuts_the_host_down(host, url, tmp_path):
    name, app_dir = host
    path = _file(tmp_path, [{"data": {"name": "Ok"}}, {"data": {"nope": 1}}])

    with pytest.raises(SystemExit):
        _import(path, "--apply", "--app", f"{name}:app", "--app-dir", app_dir)

    mod = _module(name)
    assert mod.seen == []
    assert mod.phase == ["up", "down"]
    assert asyncio.run(_count(url)) == 0


def test_a_write_without_app_warns_and_still_writes(url, tmp_path, capsys):
    path = _file(tmp_path, [{"data": {"name": "A"}}])

    assert _import(path, "--apply", "--database-url", url) == 0

    err = capsys.readouterr().err
    assert "records import: WARNING: no --app given" in err
    assert "--app main:app --app-dir host" in err
    assert asyncio.run(_count(url)) == 1


def test_a_dry_run_neither_starts_the_host_nor_warns(host, url, tmp_path, capsys):
    name, app_dir = host
    path = _file(tmp_path, [{"data": {"name": "A"}}])

    assert _import(path, "--app", f"{name}:app", "--app-dir", app_dir) == 0
    assert _import(path, "--database-url", url) == 0

    assert _module(name).phase == []
    assert "WARNING" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("no_colon", "expected MODULE:ATTR"),
        ("no_such_module_157:app", "cannot import"),
        ("{name}:missing", "has no attribute"),
        ("{name}:not_an_app", "not a SimpleModule app"),
    ],
)
def test_an_app_that_is_not_one_stops_before_writing(host, url, tmp_path, spec, message):
    name, app_dir = host
    path = _file(tmp_path, [{"data": {"name": "A"}}])

    with pytest.raises(SystemExit, match=message):
        _import(path, "--apply", "--app", spec.format(name=name), "--app-dir", app_dir)

    assert asyncio.run(_count(url)) == 0


def test_a_database_url_that_contradicts_the_app_is_refused(host, url, tmp_path):
    name, app_dir = host
    path = _file(tmp_path, [{"data": {"name": "A"}}])
    other = f"sqlite+aiosqlite:///{tmp_path / 'other.db'}"

    with pytest.raises(SystemExit, match="is not the database --app writes to"):
        _import(
            path, "--apply", "--app", f"{name}:app", "--app-dir", app_dir, "--database-url", other
        )

    # Restating the app's own database is fine.
    assert (
        _import(
            path, "--apply", "--app", f"{name}:app", "--app-dir", app_dir, "--database-url", url
        )
        == 0
    )
