"""A re-import previews an identical item as unchanged: the write's own comparison decides."""

from __future__ import annotations

from sm_events.core.tenancy import tenant_scope
from sm_events.models import Event
from sqlalchemy import update

from tests.feeds.importing import corpus
from tests.feeds.importing.runner_support import queue, read, run, stage
from tests.feeds.importing.staging_support import make_import


async def _import_twice(state, data, between=None):
    cal, first = await stage(state, data)
    await run(state, first)
    await queue(state, first)
    await run(state, first)
    if between is not None:
        await between()
    with tenant_scope("default"):
        async with state.session_factory() as db:
            second = (await make_import(db, cal, data=data)).id
            await db.commit()
    await run(state, second)
    return await read(state, second)


async def test_identical_items_preview_as_unchanged_and_nothing_is_written(events_app):
    _app, state = events_app
    imp, items, events = await _import_twice(state, corpus.simple(3))
    assert {i.verdict for i in items} == {"unchanged"}
    assert imp.counts == {"new": 0, "update": 0, "unchanged": 3, "skip": 0}
    assert {e.revision for e in events} == {1}  # the preview's dry run left no revision behind
    await queue(state, imp.id)
    await run(state, imp.id)
    done, _items, events = await read(state, imp.id)
    assert (done.unchanged, done.updated, done.created) == (3, 0, 0)
    assert {e.revision for e in events} == {1}


async def test_an_item_that_differs_previews_as_update(events_app):
    _app, state = events_app

    async def edit():
        with tenant_scope("default"):
            async with state.session_factory() as db:
                await db.execute(
                    update(Event.__table__).where(Event.uid == "u1@x").values(venue_name="Edited")
                )
                await db.commit()

    _imp, items, _events = await _import_twice(state, corpus.simple(3), edit)
    assert {i.uid: i.verdict for i in items} == {
        "u0@x": "unchanged",
        "u1@x": "update",
        "u2@x": "unchanged",
    }
