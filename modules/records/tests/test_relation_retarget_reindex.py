"""A ``relation`` re-pointed at another type, or flipped to ``many``, is
index-affecting — the rebuild is what rewrites ``records_index_ref``.
"""

from __future__ import annotations

from sm_records.models import RecordType, tables_for
from sm_records.schema.types import IndexKind
from sm_records.services import records as record_service
from sm_records.services import schema_change
from sm_records.services import types as type_service
from sm_records.services.reindex_runner import run_pending
from sqlalchemy import select

from tests.field_builders import rel, text


async def ref_rows(db, rtype: RecordType) -> list[tuple[int, str]]:
    table = tables_for(rtype).index[IndexKind.REF]
    stmt = select(table.target_type_id, table.field_key)
    return [tuple(row) for row in (await db.execute(stmt)).all()]


# ---------------------------------------------------------------------------
# retargeting a relation is index-affecting
# ---------------------------------------------------------------------------


async def test_a_retargeted_relation_enqueues_a_rebuild_that_rewrites_its_ref_rows(
    db, db_state, settings
):
    """``records_index_ref.target_type_id`` is projected from the *declared*
    target, so the edit that changes the declaration is the one that has to
    enqueue the rebuild — or ``restrict`` keeps refusing deletes on behalf of
    a field that no longer points at the type."""
    person = await type_service.create_type(
        db, key="person", label="Person", settings=settings, fields_raw=[text("name")]
    )
    company = await type_service.create_type(
        db, key="company", label="Company", settings=settings, fields_raw=[text("name")]
    )
    memo = await type_service.create_type(
        db,
        key="memo",
        label="Memo",
        settings=settings,
        fields_raw=[text("title"), rel("about", "person")],
    )
    ada = await record_service.create_record(db, person, data={"name": "Ada"}, settings=settings)
    await record_service.create_record(
        db,
        memo,
        data={"title": "m1", "about": {"type": "person", "uuid": ada.uuid}},
        settings=settings,
    )
    assert await ref_rows(db, memo) == [(person.id, "about")]

    memo_id = memo.id
    await schema_change.apply(
        db,
        memo,
        fields_raw=[text("title"), rel("about", "company")],
        expected_version=memo.version,
        settings=settings,
    )
    assert "about" in memo.reindex_pending
    await db.commit()

    assert await run_pending(db_state, memo_id, settings=settings) == 1
    assert await ref_rows(db, memo) == [(company.id, "about")]
    # And the person nothing references any more can be deleted again.
    await record_service.soft_delete_record(db, person, ada, settings=settings)


async def test_flipping_many_enqueues_the_same_rebuild(db, settings):
    """A ``many`` flip is a projection change — one ref row where there were
    several, or several where there was one — so it is marked for the same
    reason a retarget is."""
    await type_service.create_type(
        db, key="person", label="Person", settings=settings, fields_raw=[text("name")]
    )
    memo = await type_service.create_type(
        db,
        key="memo",
        label="Memo",
        settings=settings,
        fields_raw=[text("title"), rel("about", "person")],
    )
    await schema_change.apply(
        db,
        memo,
        fields_raw=[text("title"), rel("about", "person", many=True)],
        expected_version=memo.version,
        settings=settings,
    )
    assert "about" in memo.reindex_pending


async def test_changing_on_delete_still_enqueues_nothing(db, settings):
    """The counterweight: ``on_delete`` decides what a future delete does and
    changes no projected row, so it must not mark the field."""
    await type_service.create_type(
        db, key="person", label="Person", settings=settings, fields_raw=[text("name")]
    )
    memo = await type_service.create_type(
        db,
        key="memo",
        label="Memo",
        settings=settings,
        fields_raw=[text("title"), rel("about", "person", on_delete="restrict")],
    )
    await schema_change.apply(
        db,
        memo,
        fields_raw=[text("title"), rel("about", "person", on_delete="set_null")],
        expected_version=memo.version,
        settings=settings,
    )
    assert memo.reindex_pending == {}
