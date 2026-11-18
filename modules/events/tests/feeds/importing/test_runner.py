"""Leased, resumable slices: parse, then apply in batches, one savepoint per item."""

from __future__ import annotations

import pytest
from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.feeds.importing import apply as apply_module
from sm_events.feeds.importing import launch as launch_module
from sm_events.models import EventImport
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from tests.feeds.importing import corpus
from tests.feeds.importing.runner_support import (
    app_for,
    importer_keeps_stored_rights,
    queue,
    read,
    run,
    stage,
)


class Crash(BaseException):
    pass


async def test_parse_then_apply_eager(events_app, monkeypatch):
    _app, state = events_app
    monkeypatch.setattr(launch_module, "celery_eager", lambda: True)
    importer_keeps_stored_rights(monkeypatch)
    app = app_for(state)
    _cal, import_id = await stage(state, corpus.simple(4))
    await launch_module.launch(app, tenant_id="default", import_id=import_id)
    imp, items, events = await read(state, import_id)
    assert (imp.status, imp.total, imp.source, len(items), events) == ("staged", 4, None, 4, [])
    await queue(state, import_id, publish=True)
    await launch_module.launch(app, tenant_id="default", import_id=import_id)
    imp, items, events = await read(state, import_id)
    assert imp.status == "done" and imp.finished_at is not None and imp.lease_owner is None
    assert (imp.created, imp.updated, imp.unchanged, imp.skipped, imp.failed, imp.processed) == (
        4,
        0,
        0,
        0,
        0,
        4,
    )
    assert [i.outcome for i in items] == ["created"] * 4 and all(i.event_id for i in items)
    assert [e.uid for e in events] == [f"u{n}@x" for n in range(4)]
    assert {e.status for e in events} == {"published"}


async def test_reapplying_the_same_file_changes_nothing(events_app):
    _app, state = events_app
    data = corpus.simple(3)
    _cal, first = await stage(state, data)
    await run(state, first)
    await queue(state, first)
    assert await run(state, first) == "done"
    # The same bytes again into the same calendar: every item is an update that changes nothing.
    from tests.feeds.importing.runner_support import PUBLISHER
    from tests.feeds.importing.staging_support import make_import

    async with state.session_factory() as db:
        cal = (await read(state, first))[2][0].calendar_id
        from sm_events.models import Calendar

        calendar = (await db.execute(select(Calendar).where(Calendar.id == cal))).scalar_one()
        second = (await make_import(db, calendar, data=data)).id
        await db.commit()
    await run(state, second)
    imp, items, _ = await read(state, second)
    assert [i.verdict for i in items] == ["unchanged"] * 3  # the write itself says so
    await queue(state, second, grants=PUBLISHER)
    assert await run(state, second) == "done"
    imp, items, events = await read(state, second)
    assert (imp.unchanged, imp.created, imp.updated) == (3, 0, 0)
    assert [i.outcome for i in items] == ["unchanged"] * 3 and len(events) == 3


async def test_slices_resume(events_app, monkeypatch):
    _app, state = events_app
    monkeypatch.setattr(constants, "IMPORT_APPLY_BATCH", 2)
    _cal, import_id = await stage(state, corpus.simple(5))
    await run(state, import_id)
    await queue(state, import_id)
    ticks = iter(range(10**6))
    expired = lambda: next(ticks) * 1000.0  # noqa: E731 - every look at the clock is a long time
    answers = [await run(state, import_id, clock=expired) for _ in range(3)]
    assert answers == ["more", "more", "done"]
    imp, _items, events = await read(state, import_id)
    assert (imp.status, imp.processed, len(events)) == ("done", 5, 5)


async def test_crash_mid_batch_resumes(events_app, monkeypatch):
    _app, state = events_app
    monkeypatch.setattr(constants, "IMPORT_APPLY_BATCH", 4)
    _cal, import_id = await stage(state, corpus.simple(6))
    await run(state, import_id)
    await queue(state, import_id)
    real = apply_module.write_item
    calls = {"n": 0}

    async def dying(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise Crash
        return await real(*args, **kwargs)

    monkeypatch.setattr(apply_module, "write_item", dying)
    with pytest.raises(Crash):
        await run(state, import_id)
    imp, items, events = await read(state, import_id)
    assert imp.status == "running" and events == [] and all(i.outcome is None for i in items)
    monkeypatch.setattr(apply_module, "write_item", real)
    assert await run(state, import_id) == "busy"  # the dead worker's lease is still live
    later = lambda: utcnow() + constants.IMPORT_LEASE * 2  # noqa: E731
    assert await run(state, import_id, now=later) == "done"
    imp, items, events = await read(state, import_id)
    assert (imp.created, imp.processed, len(events)) == (6, 6, 6)
    assert len({e.uid for e in events}) == 6  # nothing twice


async def test_item_failure_isolated(events_app, monkeypatch):
    _app, state = events_app
    _cal, import_id = await stage(state, corpus.simple(3))
    await run(state, import_id)
    await queue(state, import_id)
    real = apply_module.write_item

    async def flaky(db, imp, item, **kwargs):
        if item.uid == "u1@x":
            raise IntegrityError("INSERT", {}, Exception("secret value u1@x"))
        return await real(db, imp, item, **kwargs)

    monkeypatch.setattr(apply_module, "write_item", flaky)
    assert await run(state, import_id) == "done"
    imp, items, events = await read(state, import_id)
    by_uid = {i.uid: (i.outcome, i.outcome_code) for i in items}
    assert by_uid == {
        "u0@x": ("created", None),
        "u1@x": ("failed", "write_failed"),
        "u2@x": ("created", None),
    }
    assert (imp.created, imp.failed, imp.processed) == (2, 1, 3)
    assert [e.uid for e in events] == ["u0@x", "u2@x"]


async def test_skips_are_outcomes_with_codes(events_app):
    _app, state = events_app
    data = corpus.calendar(*corpus.vevent("ok@x"), *corpus.vevent("bad@x", "RRULE:FREQ=SECONDLY"))
    _cal, import_id = await stage(state, data)
    await run(state, import_id)
    await queue(state, import_id)
    await run(state, import_id)
    imp, items, _ = await read(state, import_id)
    assert {i.uid: (i.outcome, i.outcome_code) for i in items} == {
        "ok@x": ("created", None),
        "bad@x": ("skipped", "unsupported_rule"),
    }
    assert (imp.created, imp.skipped) == (1, 1)


async def test_rights_lost_before_the_apply_skip_every_item(events_app):
    _app, state = events_app
    _cal, import_id = await stage(state, corpus.simple(2))
    await run(state, import_id)
    await queue(state, import_id, grants=("events.view",))  # no longer a manager
    await run(state, import_id)
    imp, items, events = await read(state, import_id)
    assert [(i.outcome, i.outcome_code) for i in items] == [("skipped", "forbidden")] * 2
    assert events == [] and imp.skipped == 2


@pytest.mark.unbound_tenant
async def test_slice_binds_import_tenant(events_app):
    from sm_events.core.tenancy import tenant_scope

    _app, state = events_app
    _a, a_id = await stage(state, corpus.simple(2), tenant="a")
    _b, b_id = await stage(state, corpus.simple(2), tenant="b")
    with tenant_scope("a"):  # the caller's tenant is bound: the slice must not follow it
        assert await run(state, b_id, tenant="b") == "done"
        assert await run(state, a_id, tenant="b") == "gone"  # a's id is no import of b
    await queue(state, b_id, tenant="b")
    with tenant_scope("a"):
        await run(state, b_id, tenant="b")
    imp, _items, events = await read(state, b_id, tenant="b")
    assert imp.status == "done" and [e.tenant_id for e in events] == ["b", "b"]
    _imp_a, _items_a, events_a = await read(state, a_id, tenant="a")
    assert events_a == []


async def test_lost_lease_writes_nothing(tmp_path, monkeypatch):
    from tests.pg_support import make_db_state

    # One connection per session: the thief's commit must not commit the batch's work too.
    state = await make_db_state(file=tmp_path / "lease.db")
    _cal, import_id = await stage(state, corpus.simple(2))
    await run(state, import_id)
    await queue(state, import_id)
    real = apply_module.write_item

    stolen_once = {"done": False}

    async def stolen(db, imp, item, **kwargs):
        if not stolen_once["done"]:  # before the batch has written anything (SQLite's one writer)
            stolen_once["done"] = True
            async with state.session_factory() as other:  # another worker takes the lease
                table = EventImport.__table__
                await other.execute(update(table).values(lease_owner="thief"))
                await other.commit()
        return await real(db, imp, item, **kwargs)

    monkeypatch.setattr(apply_module, "write_item", stolen)
    assert await run(state, import_id) == "busy"
    imp, items, events = await read(state, import_id)
    assert events == [] and all(i.outcome is None for i in items)
    assert imp.lease_owner == "thief" and imp.processed == 0
    await state.engine.dispose()


async def test_calendar_trashed_mid_import_fails(events_app):
    from sm_events.models import Calendar

    _app, state = events_app
    cal, import_id = await stage(state, corpus.simple(2))
    await run(state, import_id)
    await queue(state, import_id)
    async with state.session_factory() as db:
        row = (await db.execute(select(Calendar).where(Calendar.id == cal.id))).scalar_one()
        row.is_deleted = True
        await db.commit()
    assert await run(state, import_id) == "done"
    imp, _items, events = await read(state, import_id)
    assert (imp.status, imp.error_code, events) == ("failed", "import_failed", [])


async def test_a_failing_parse_is_recorded_not_raised(events_app):
    _app, state = events_app
    _cal, import_id = await stage(state, corpus.invalid_utf8())
    assert await run(state, import_id) == "done"
    imp, items, _ = await read(state, import_id)
    assert (imp.status, imp.error_code, items) == ("failed", "ics_encoding", [])


async def test_nothing_to_do_for_a_finished_import(events_app):
    _app, state = events_app
    _cal, import_id = await stage(state, corpus.simple(1))
    await run(state, import_id)
    assert await run(state, import_id) == "gone"  # staged: nothing claimable
    assert await run(state, 99999) == "gone"


async def test_non_eager_enqueues(events_app, monkeypatch):
    from sm_events import tasks

    _app, state = events_app
    sent: list[tuple] = []

    class Signature:
        def __init__(self, args):
            self.args = args

        def apply_async(self, **kwargs):
            sent.append((self.args, kwargs))

    class Fake:
        @staticmethod
        def s(*args):
            return Signature(args)

    monkeypatch.setattr(launch_module, "celery_eager", lambda: False)
    monkeypatch.setattr(tasks, "run_import", Fake)
    _cal, import_id = await stage(state, corpus.simple(1))
    await launch_module.launch(app_for(state), tenant_id="default", import_id=import_id)
    assert sent == [((("default", import_id)), {"queue": "events"})]
    imp, _items, _events = await read(state, import_id)
    assert imp.status == "uploaded"  # nothing ran inline
