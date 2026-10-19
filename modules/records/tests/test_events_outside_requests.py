"""Events from the write paths that have no request: CLI import, the seeder (GH #128).

The services emit (:mod:`sm_records.events`), so these paths publish through
the same ``on_commit`` queue the HTTP endpoints do — to whatever bus the
caller attached. Asserted here: a CLI import publishes ``RecordCreated`` and
``RecordUpdated``, the events carry the uuid a file chose, a dry run or a
refused import publishes nothing, a write rolled back publishes nothing, a
row whose savepoint rolled back publishes nothing, and the seeder publishes
one ``RecordCreated`` per record it wrote.

The exactly-once half for HTTP is ``test_events.py``: every test there asserts
the full list of what one request published.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from simple_module_core.events import EventBus
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sm_records import events
from sm_records.cli_io import import_command
from sm_records.contracts.events import (
    RecordCreated,
    RecordPurged,
    RecordTypeDeleted,
    RecordUpdated,
)
from sm_records.models import Base, Record, RecordType
from sm_records.seed import seed_database
from sm_records.services.errors import Conflict
from sm_records.services.records import create_record
from sm_records.settings import RecordsSettings
from sqlalchemy import select

FIELDS = [
    {"key": "name", "type": "text", "label": "Name", "indexed": True},
    {"key": "price", "type": "number", "label": "Price"},
]
SETTINGS = RecordsSettings()


class Seen:
    """A bus and everything published on it, in order."""

    def __init__(self) -> None:
        self.bus = EventBus()
        self.events: list[Any] = []
        for event_type in (RecordCreated, RecordUpdated, RecordPurged, RecordTypeDeleted):
            self.bus.subscribe(event_type, self._handle)

    async def _handle(self, event: Any) -> None:
        self.events.append(event)

    def of(self, event_type: type) -> list[Any]:
        return [event for event in self.events if isinstance(event, event_type)]


def _state(url: str) -> Any:
    state = init_db(url)
    register_listeners(state)
    return state


@pytest.fixture
async def widget_db(tmp_path) -> str:
    """A ``widget`` type with one record, in a file the CLI opens itself."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'events.db'}"
    state = _state(url)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with state.session_factory() as session:
        rtype = RecordType(
            key="widget", label="Widget", label_plural="Widgets", fields=FIELDS, schema_version=1
        )
        session.add(rtype)
        await session.flush()
        await create_record(session, rtype, data={"name": "Old", "price": "1"}, settings=SETTINGS)
        await session.commit()
    await state.engine.dispose()
    return url


async def _import(url: str, path: Any, seen: Seen, *, apply: bool = True, **kw: Any) -> Any:
    return await import_command(
        url,
        "widget",
        str(path),
        mode=kw.get("mode", "upsert"),
        on_error=kw.get("on_error", "abort"),
        match_by="uuid",
        force=kw.get("force", False),
        apply=apply,
        bus=seen.bus,
    )


async def _only_record(url: str) -> Record:
    state = _state(url)
    try:
        async with state.session_factory() as session:
            rows = (await session.execute(select(Record).order_by(Record.id))).scalars().all()
            return rows[0]
    finally:
        await state.engine.dispose()


async def test_a_cli_import_publishes_record_created_with_the_files_uuid(widget_db, tmp_path):
    chosen = "0" * 31 + "1"
    path = tmp_path / "new.json"
    path.write_text(
        json.dumps({"records": [{"data": {"name": "New"}}, {"uuid": chosen, "data": {}}]})
    )
    seen = Seen()

    report = await _import(widget_db, path, seen)

    assert report.created == 2
    created = seen.of(RecordCreated)
    assert [type(event) for event in seen.events] == [RecordCreated, RecordCreated]
    assert {event.type_key for event in created} == {"widget"}
    assert {event.tenant_id for event in created} == {"default"}
    # Built after the importer re-stamped the uuid — not the one
    # ``create_record`` generated and the file then replaced.
    assert created[1].uuid == chosen
    assert created[1].translation_group == chosen


async def test_a_cli_import_update_publishes_record_updated(widget_db, tmp_path):
    record = await _only_record(widget_db)
    path = tmp_path / "update.json"
    path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "uuid": record.uuid,
                        "version": record.version,
                        "status": "published",
                        "data": {"name": "Renamed", "price": "2"},
                    }
                ]
            }
        )
    )
    seen = Seen()

    report = await _import(widget_db, path, seen)

    assert report.updated == 1
    [event] = seen.events
    assert isinstance(event, RecordUpdated)
    assert (event.uuid, event.version) == (record.uuid, record.version + 1)
    # Read before the write, now that the service — not a file-level summary
    # — builds it: the status the record actually had.
    assert (event.status_before, event.status_after) == ("draft", "published")


async def test_a_dry_run_or_refused_import_publishes_nothing(widget_db, tmp_path):
    path = tmp_path / "new.json"
    path.write_text(json.dumps({"records": [{"data": {"name": "New"}}]}))
    seen = Seen()
    await _import(widget_db, path, seen, apply=False)

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"records": [{"data": {"name": "Ok"}}, {"data": {"nope": 1}}]}))
    with pytest.raises(SystemExit):
        await _import(widget_db, bad, seen)

    assert seen.events == []


async def test_a_write_rolled_back_publishes_nothing(db_state):
    seen = Seen()
    async with db_state.session_factory() as session:
        events.attach(session, seen.bus)
        rtype = RecordType(key="note", label="Note", label_plural="Notes", fields=FIELDS)
        session.add(rtype)
        await session.flush()
        await create_record(session, rtype, data={"name": "Gone"}, settings=SETTINGS)
        await events.rollback(session)
        # Nothing left to commit, and nothing left queued for the commit.
        await events.commit(session)
    assert seen.events == []


async def test_a_row_whose_savepoint_rolled_back_publishes_nothing(db_state):
    """What an import's ``on_error=skip`` relies on: the framework's queue is
    session-wide and blind to ``begin_nested``, ``held`` is not."""
    seen = Seen()
    async with db_state.session_factory() as session:
        events.attach(session, seen.bus)
        rtype = RecordType(key="note", label="Note", label_plural="Notes", fields=FIELDS)
        session.add(rtype)
        await session.flush()
        with pytest.raises(Conflict), events.held(session):
            async with session.begin_nested():
                await create_record(session, rtype, data={"name": "Skip"}, settings=SETTINGS)
                raise Conflict("refused after the create")
        # The savepoint's rollback expired the type row, as in the importer.
        await session.refresh(rtype)
        with events.held(session):
            async with session.begin_nested():
                kept = await create_record(session, rtype, data={"name": "Keep"}, settings=SETTINGS)
        await events.commit(session)
    assert [event.uuid for event in seen.events] == [kept.uuid]


async def test_the_seeder_publishes_one_record_created_per_record(db_state, settings):
    seen = Seen()
    summary = await seed_database(db_state, settings, records=40, seed=3, reset=True, bus=seen.bus)
    assert len(seen.of(RecordCreated)) == summary.total

    again = Seen()
    await seed_database(db_state, settings, records=40, seed=3, reset=True, bus=again.bus)
    purged, deleted = again.of(RecordPurged), again.of(RecordTypeDeleted)
    assert len(purged) == summary.total
    assert {event.type_key for event in deleted} == set(summary.created)
    # Each type's purges ahead of its own deletion, as on the HTTP path.
    first_delete = again.events.index(deleted[0])
    assert all(isinstance(event, RecordPurged) for event in again.events[:first_delete])
