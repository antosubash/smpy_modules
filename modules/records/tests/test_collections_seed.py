"""The demo seeder's sixth type, which lives in a collection — §6.6.

``event`` is declared in ``sm_records.seed.types`` with ``collection="events"``
and is created **only where that collection is declared**
(:func:`~sm_records.seed.types.active_type_defs`). Two things follow, and both
are asserted here:

* on this process — which declares ``events`` at import
  (``tests/collections_harness.py``) — the seeder writes six types and its
  ``event`` records land in ``records_c_events_record``;
* ``--records N`` still writes exactly N records, because ``event``'s share is
  taken proportionally from the five rather than added on top.

The five-type case is ``test_seed.py``'s, which runs in the same process and
therefore has to be collection-aware too — it is, through the same helper.
"""

from __future__ import annotations

import pytest
from sm_records.models import GLOBAL, RecordType, tables_for
from sm_records.seed import seed_database
from sm_records.seed.plan import WEIGHTS, distribute, weights_for
from sqlalchemy import func, select

from tests.collections_harness import EVENTS


async def _types(db) -> dict[str, RecordType]:
    rows = (await db.execute(select(RecordType))).scalars().all()
    return {row.key: row for row in rows}


async def _count(db, cls) -> int:
    return int((await db.execute(select(func.count(cls.id)))).scalar_one())


async def test_the_seeder_creates_the_event_type_in_the_events_collection(db_state, settings, db):
    await seed_database(db_state, settings, records=120, seed=5, reset=True)

    types = await _types(db)
    assert set(types) == {"company", "contact", "product", "store", "order", "event"}
    assert types["event"].collection == "events"
    assert tables_for(types["event"]) is EVENTS
    for key in ("company", "contact", "product", "store", "order"):
        assert types[key].collection is None


async def test_event_records_land_in_the_collections_table(db_state, settings, db):
    summary = await seed_database(db_state, settings, records=120, seed=5, reset=True)

    assert summary.created["event"] >= 1
    assert await _count(db, EVENTS.record) == summary.created["event"]
    assert await _count(db, GLOBAL.record) == summary.total - summary.created["event"]


async def test_the_total_is_still_exactly_what_was_asked_for(db_state, settings):
    """``event``'s share is taken *proportionally* from the five, not added on
    top, so ``--records N`` means N whether or not a collection is declared."""
    summary = await seed_database(db_state, settings, records=120, seed=5, reset=True)
    assert summary.total == 120


async def test_an_events_venue_points_at_a_global_store(db_state, settings, db):
    """The demo graph's one cross-collection relation (§6.4): ``event.venue``
    is a ``relation`` to ``store``, which is global."""
    await seed_database(db_state, settings, records=200, seed=6, reset=True)

    types = await _types(db)
    stores = (
        (await db.execute(select(GLOBAL.record).where(GLOBAL.record.type_id == types["store"].id)))
        .scalars()
        .all()
    )
    store_uuids = {row.uuid for row in stores}
    events = (
        (await db.execute(select(EVENTS.record).where(EVENTS.record.type_id == types["event"].id)))
        .scalars()
        .all()
    )
    assert events
    for row in events:
        venue = (row.data or {}).get("venue")
        if venue is not None:
            assert venue["type"] == "store"
            assert venue["uuid"] in store_uuids


async def test_reset_purges_the_collections_records_too(db_state, settings, db):
    await seed_database(db_state, settings, records=120, seed=5, reset=True)
    assert await _count(db, EVENTS.record) > 0

    await seed_database(db_state, settings, records=0, seed=5, reset=True)
    assert await _count(db, EVENTS.record) == 0
    assert await _count(db, GLOBAL.record) == 0


def test_the_weights_are_phase_4s_when_no_collection_is_declared():
    """The arithmetic half of "inert when unused" (§6.5): the five weights are
    used unchanged, so a host with no collections gets the counts it always
    did."""
    assert weights_for({"company", "contact", "product", "store", "order"}) == WEIGHTS
    with_event = weights_for({*WEIGHTS, "event"})
    assert with_event["event"] == pytest.approx(0.05)
    assert sum(with_event.values()) == pytest.approx(1.0)
    assert sum(distribute(100, with_event).values()) == 100
