"""The write path: what one ``create_record`` costs, and where it goes.

The interesting number here is not the wall clock — SQLite's single writer
dominates that — but the **statement count per write**, which is a property of
the module's code and identical on Postgres. Everything asserted is a shape:
the count is constant in the table size, and it does not grow with the number
of records already stored.
"""

from __future__ import annotations

import itertools
from uuid import uuid4

import pytest
from sm_records.models import RecordStatus, RevisionEvent
from sm_records.seed.data import PRODUCT_CATEGORIES, TAG_POOL
from sm_records.services import records as record_service
from sm_records.services._common import type_id_map

from tests.perf._bench import Results, capture, repeat
from tests.perf.conftest import REPS, load_type, type_counts

pytestmark = pytest.mark.perf


_SEQ = itertools.count(uuid4().int % 1_000_000_000)
"""Run-unique so repeated runs against the same (persistent) perf database
never collide on ``company.name``'s slug or ``product.sku``'s uniqueness —
both are real constraints the write path checks, and a collision would be
measured as a refusal rather than a write."""


def _next() -> int:
    return next(_SEQ)


def _company(i: int) -> dict:
    return {
        "name": f"Perf Bench Holdings {i}",
        "state": "CA",
        "city": "Palo Alto",
        "founded": "1999-04-01",
        "employees": 120 + i,
        "annual_revenue": "1234567.50000",
        "website": "https://example.com",
        "is_public": True,
        "description": "A company created by the perf suite.",
    }


def _product(i: int) -> dict:
    return {
        "sku": f"PERF-{i:09d}",
        "name": f"Perf Widget {i}",
        "category": PRODUCT_CATEGORIES[0],
        "price": "19.99000",
        "in_stock": True,
        "tags": [TAG_POOL[0], TAG_POOL[1]],
        "weight_lbs": "2.50000",
        "specs": {"color": "black"},
    }


async def _create(session, rtype, settings, payload):
    record = await record_service.create_record(
        session, rtype, data=payload, settings=settings, status=RecordStatus.PUBLISHED
    )
    await session.commit()
    return record


async def test_create_throughput_and_statements(perf_db, perf_session, settings):
    """``create_record`` on a type with a unique field and one with a relation.

    ``company`` has no unique field and no relation; ``product`` has a unique
    ``sku``. The pair isolates what ``ensure_unique`` costs.
    """
    counts = await type_counts(perf_session)
    total = sum(counts.values())

    for key, builder in (("company", _company), ("product", _product)):
        rtype = await load_type(perf_session, key)

        async def one(rtype=rtype, builder=builder):
            await _create(perf_session, rtype, settings, builder(_next()))

        timing = await repeat(one, reps=REPS, warmup=3)
        with capture(perf_db.engine) as box:
            await _create(perf_session, rtype, settings, builder(_next()))
        Results.add(
            f"create_record({key})",
            total,
            timing,
            statements=box.count,
            plan=f"{1000.0 / max(timing.p50, 1e-9):.0f} rec/s",
        )
        # A create issues a bounded set of round trips — validate, lock, type
        # map, relation targets, unique, slug, insert, revision, trim, index.
        # The ceiling is loose on purpose; the assertion that matters is that
        # it does not scale with the table.
        assert box.count < 40, f"{key}: {box.count} statements per create"


async def test_create_statement_count_is_flat(perf_db, perf_session, settings):
    """The same create, measured on the 1st and the 200th row written in this
    test: the count must not move. A per-write cost that grows with the type's
    size is the failure this guards."""
    rtype = await load_type(perf_session, "company")

    async def one():
        await _create(perf_session, rtype, settings, _company(_next()))

    with capture(perf_db.engine) as first:
        await one()
    for _ in range(50):
        await one()
    with capture(perf_db.engine) as later:
        await one()
    assert first.count == later.count, (
        f"per-create statement count moved from {first.count} to {later.count}"
    )
    Results.note(f"create_record statement count constant at {first.count} statements")


async def test_update_with_and_without_indexed_change(perf_db, perf_session, settings):
    """An indexed-field change against a no-op edit.

    ``write_index`` deletes and reinserts a record's whole index row set on
    *every* write, so the two should cost the same — which is the point worth
    recording, not a difference.
    """
    rtype = await load_type(perf_session, "product")
    counts = await type_counts(perf_session)
    serial = _next()
    record = await _create(perf_session, rtype, settings, _product(serial))
    state = {"version": record.version, "n": 0}

    async def touch(change_indexed: bool):
        state["n"] += 1
        payload = _product(serial)
        if change_indexed:
            payload["price"] = f"{10 + state['n'] % 50}.00000"
        updated = await record_service.update_record(
            perf_session,
            rtype,
            record,
            expected_version=state["version"],
            data=payload,
            settings=settings,
            event=RevisionEvent.UPDATE,
        )
        state["version"] = updated.version
        await perf_session.commit()

    for label, flag in (
        ("update_record(no indexed change)", False),
        ("update_record(price)", True),
    ):
        timing = await repeat(lambda flag=flag: touch(flag), reps=REPS, warmup=3)
        with capture(perf_db.engine) as box:
            await touch(flag)
        Results.add(label, sum(counts.values()), timing, statements=box.count)


async def test_delete_restore_purge(perf_db, perf_session, settings):
    """Trash, restore, purge — the three lifecycle writes, one record each.

    ``company`` is chosen because nothing in the demo dataset relates *to* the
    companies the perf suite creates, so the referrer walk is the empty case;
    a delete of a ``contact`` with orders pointing at it is the restrict path
    and is measured separately below.
    """
    rtype = await load_type(perf_session, "company")
    counts = await type_counts(perf_session)
    total = sum(counts.values())

    async def cycle():
        record = await _create(perf_session, rtype, settings, _company(_next()))
        await record_service.soft_delete_record(perf_session, rtype, record, settings=settings)
        await perf_session.commit()
        await record_service.restore_record(perf_session, rtype, record, settings=settings)
        await perf_session.commit()
        await record_service.soft_delete_record(perf_session, rtype, record, settings=settings)
        await perf_session.commit()
        await record_service.hard_delete_record(perf_session, rtype, record)
        await perf_session.commit()

    timing = await repeat(cycle, reps=max(REPS // 2, 5), warmup=2)
    with capture(perf_db.engine) as box:
        await cycle()
    Results.add("delete+restore+delete+purge cycle", total, timing, statements=box.count)
    Results.note(
        f"purge issues {len(box.matching('DELETE FROM records_index'))} index DELETEs "
        "(one per kind table) per record"
    )


async def test_type_id_map_per_write(perf_db, perf_session):
    """``type_id_map`` is a full read of ``records_type`` and the write path
    calls it twice per record (once for the relation check, once to build the
    index writer's resolver). Recorded, not asserted — the table is tiny, but
    the count is the evidence for the finding."""
    with capture(perf_db.engine) as box:
        await type_id_map(perf_session)
    assert box.count == 1
    Results.note("type_id_map is 1 SELECT over records_type; create_record runs it twice")
