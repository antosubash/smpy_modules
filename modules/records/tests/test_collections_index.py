"""The index layers over a collection type: reindex, reduce, and the public API.

Three things the table-set refactor had to carry that the CRUD file does not
cover:

* the **rebuild** (``reindex_type``) reads the collection's documents and
  writes the collection's index rows — never the global ones;
* the **reduce index** stays global (§6.4), keyed by ``type_id``, and is folded
  from a collection's records all the same;
* the **anonymous read API** works on a public collection type, which matters
  because that path has its own statement builder (``services.public``) whose
  published predicate used to be a module-level bound column.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sm_records.index.reduce import ReduceSpec, register_reduce_provider
from sm_records.index.reduce_rebuild import recompute, verify_type
from sm_records.index.reindex import reindex_type
from sm_records.models import GLOBAL, IndexReduce, tables_for
from sm_records.schema.types import IndexKind
from sm_records.services import records as record_service
from sm_records.services import reindex_runner
from sm_records.services.reindex_runner import _recompute_titles
from sm_records.settings import RecordsSettings
from sqlalchemy import func, select

from tests.app_harness import ADMIN, roles, seed_type
from tests.collections_harness import EVENTS, make_collection_record


@pytest.fixture
def settings() -> RecordsSettings:
    return RecordsSettings()


@pytest.fixture
async def gig(make_type, field_def):
    return await make_type(
        "gig",
        [field_def("name", "text"), field_def("capacity", "integer")],
        collection="events",
        display_field="name",
    )


async def _count(db, cls) -> int:
    return int((await db.execute(select(func.count(cls.id)))).scalar_one())


async def test_a_rebuild_writes_the_collections_index_and_not_the_global_one(db, gig):
    """The records are inserted straight into the collection's document table
    with no index rows at all — exactly the state a schema change leaves — so
    what the rebuild produces is the whole assertion."""
    for i in range(3):
        await make_collection_record(db, gig, {"name": f"Gig {i}", "capacity": i})

    written = await reindex_type(db, gig, resolve_type_id=lambda _k: None, batch_size=2)
    assert written == 3

    tables = tables_for(gig)
    assert tables is EVENTS
    assert await _count(db, tables.index[IndexKind.TEXT]) == 3
    assert await _count(db, tables.index[IndexKind.NUMBER]) == 3
    assert await _count(db, GLOBAL.index[IndexKind.TEXT]) == 0
    assert await _count(db, GLOBAL.index[IndexKind.NUMBER]) == 0


async def test_the_title_rebuild_walks_the_collections_documents(db, gig):
    """``display_title`` is denormalised onto the record row, so the ``"*"``
    marker's rebuild (§8.9) walks documents rather than index rows — which
    means it needs the collection's record table and not the global one."""
    record = await make_collection_record(db, gig, {"name": "Launch", "capacity": 1})
    assert record.display_title == ""
    assert await _recompute_titles(db, gig, 10) == 1
    await db.refresh(record)
    assert record.display_title == "Launch"


async def test_the_reduce_index_stays_global_and_folds_a_collections_records(db, gig, settings):
    """§6.4: a reduce row is keyed by ``type_id`` with no ``record_id`` to
    partition on, so it lives in ``records_index_reduce`` whatever table set
    its records came out of — and the verifier, which recomputes from those
    records, has to agree."""
    spec = ReduceSpec(
        key="gigs_by_size",
        group_by=lambda record, rtype: (
            "big" if (record.data or {}).get("capacity", 0) >= 100 else "small"
        ),
        value=lambda record, rtype: Decimal((record.data or {}).get("capacity") or 0),
    )
    register_reduce_provider(spec)
    for capacity in (10, 20, 500):
        await record_service.create_record(
            db, gig, data={"name": f"Gig {capacity}", "capacity": capacity}, settings=settings
        )

    rows = (await db.execute(select(IndexReduce).where(IndexReduce.type_id == gig.id))).scalars()
    stored = {row.group_value: (row.count, row.sum) for row in rows}
    assert stored == {"small": (2, Decimal(30)), "big": (1, Decimal(500))}
    assert stored == await recompute(db, gig, spec, batch_size=10)
    assert await verify_type(db, gig, batch_size=10) == []


async def test_trashing_a_collection_record_takes_it_out_of_the_reduce_index(db, gig, settings):
    register_reduce_provider(
        ReduceSpec(key="gigs", group_by=lambda record, rtype: "all", value=None)
    )
    record = await record_service.create_record(
        db, gig, data={"name": "Launch", "capacity": 1}, settings=settings
    )
    await record_service.soft_delete_record(db, gig, record, settings=settings)

    row = (
        (await db.execute(select(IndexReduce).where(IndexReduce.type_id == gig.id)))
        .scalars()
        .first()
    )
    assert row is None or row.count == 0
    assert await verify_type(db, gig, batch_size=10) == []


async def test_the_anonymous_read_api_serves_a_public_collection_type(client, field_def):
    rtype = await seed_type(
        client.db_state,
        "gig",
        [field_def("name", "text"), field_def("capacity", "integer")],
        collection="events",
        display_field="name",
        slug_field="name",
        is_public=True,
    )
    module = client.app.state.records_module
    await module.on_startup(client.app)

    created = await client.post(
        "/api/records/types/gig/records",
        json={"data": {"name": "Launch", "capacity": 200}, "status": "published", "slug": "launch"},
        headers=roles(ADMIN),
    )
    assert created.status_code == 201
    draft = await client.post(
        "/api/records/types/gig/records",
        json={"data": {"name": "Secret", "capacity": 1}},
        headers=roles(ADMIN),
    )
    assert draft.status_code == 201

    listed = await client.get("/api/records/public/gig")
    assert listed.status_code == 200
    body = listed.json()
    # Published only — the draft is not in the list and its count is not in
    # the total, both halves narrowed by the same predicate.
    assert [item["slug"] for item in body["items"]] == ["launch"]
    assert body["total"] == 1

    one = await client.get(f"/api/records/public/gig/{created.json()['uuid']}")
    assert one.status_code == 200
    assert one.json()["display_title"] == "Launch"

    hidden = await client.get(f"/api/records/public/gig/{draft.json()['uuid']}")
    assert hidden.status_code == 404

    filtered = await client.get("/api/records/public/gig?filter=capacity:gte:100")
    assert [item["slug"] for item in filtered.json()["items"]] == ["launch"]
    assert rtype.collection == "events"


async def test_the_out_of_request_runner_rebuilds_a_collection_type(
    db, db_state, settings, field_def
):
    """The CLI's actual work (``reindex_runner.run_pending``) — "the CLI takes
    a type and follows its collection", §6.4.

    §8.4 end to end, inside a collection: the payload keeps the string ``"12"``
    forever, the rebuild writes ``12`` into the collection's *number* index and
    empties its *text* one, and neither global table is touched.
    """
    from sm_records.services import schema_change
    from sm_records.services import types as type_service

    gig = await type_service.create_type(
        db,
        key="gig",
        label="Gig",
        collection="events",
        fields_raw=[field_def("capacity", "text")],
        settings=settings,
    )
    record = await record_service.create_record(db, gig, data={"capacity": "12"}, settings=settings)
    type_id, record_id = gig.id, record.id
    tables = tables_for(gig)
    text, number = tables.index[IndexKind.TEXT], tables.index[IndexKind.NUMBER]
    assert await _count(db, text) == 1

    await schema_change.apply(
        db,
        gig,
        fields_raw=[field_def("capacity", "number")],
        expected_version=gig.version,
        settings=settings,
    )
    await db.commit()

    assert await reindex_runner.run_pending(db_state, type_id, settings=settings) == 1

    assert await _count(db, text) == 0
    assert await _count(db, number) == 1
    assert await _count(db, GLOBAL.index[IndexKind.NUMBER]) == 0
    # The payload never moved (§8.3).
    payload = (
        await db.execute(select(tables.record.data).where(tables.record.id == record_id))
    ).scalar_one()
    assert payload["capacity"] == "12"
