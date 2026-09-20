"""Phase 5 core review — the schema half. Each test failed before its fix.

Two findings, both about a schema edit and what it must (and must not) set in
motion:

* a ``relation`` re-pointed at another type, or flipped to ``many``, is
  index-affecting — the rebuild is what rewrites ``records_index_ref``;
* a finished preview report belongs to a ``type_id``, never to a ``type_key``,
  so a type deleted and recreated under one reuses nothing.

The import and expansion halves are in
``test_review_fixes_round5_io.py``.
"""

from __future__ import annotations

import pytest
from sm_records.models import RecordType, tables_for
from sm_records.schema.changes import DryRunReport, SchemaDiff
from sm_records.schema.types import IndexKind
from sm_records.services import preview_jobs, schema_change
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.services._preview import reused_report
from sm_records.services.reindex_runner import run_pending
from sm_records.settings import RecordsSettings
from sqlalchemy import select

from tests.round5_helpers import rel, text


@pytest.fixture
def settings() -> RecordsSettings:
    return RecordsSettings()


async def ref_rows(db, rtype: RecordType) -> list[tuple[int, str]]:
    table = tables_for(rtype).index[IndexKind.REF]
    stmt = select(table.target_type_id, table.field_key)
    return [tuple(row) for row in (await db.execute(stmt)).all()]


# ---------------------------------------------------------------------------
# 1 — retargeting a relation is index-affecting
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


# ---------------------------------------------------------------------------
# 5 — a preview report is reused by type_id
# ---------------------------------------------------------------------------


@pytest.fixture
def jobs():
    """The registry is process-global (see its docstring), so a test that
    starts a job must leave it as it found it."""
    preview_jobs._jobs.clear()
    yield preview_jobs
    preview_jobs._jobs.clear()


def finished(jobs, *, type_key: str, type_id: int, version: int, signature: str):
    job = jobs.start(
        type_key=type_key,
        type_id=type_id,
        type_version=version,
        signature=signature,
        total=0,
        ttl_seconds=600,
    )
    jobs.finish(job.id, SchemaDiff(changes=()), DryRunReport(checked=3, failing=0))
    return job


def test_a_report_is_reused_by_type_id_and_not_by_key(jobs):
    job = finished(jobs, type_key="note", type_id=7, version=1, signature="sig")
    assert jobs.reusable(type_id=7, type_version=1, signature="sig", ttl_seconds=600) is job
    assert jobs.reusable(type_id=8, type_version=1, signature="sig", ttl_seconds=600) is None


async def test_a_type_deleted_and_recreated_under_the_same_key_reuses_nothing(db, jobs, settings):
    """A key is not an identity: the recreated type restarts at ``version =
    1``, so key-and-version alone matched a report taken over records that no
    longer exist."""
    fields = [text("title")]
    gone = await type_service.create_type(
        db, key="note", label="Note", settings=settings, fields_raw=fields
    )
    signature = jobs.fields_hash(list(gone.fields or []), gone.display_field, gone.slug_field)
    finished(jobs, type_key="note", type_id=gone.id, version=gone.version, signature=signature)
    assert (
        reused_report(
            gone,
            current_version=gone.version,
            fields_raw=list(gone.fields or []),
            display_field=gone.display_field,
            slug_field=gone.slug_field,
            settings=settings,
            drop_keys=frozenset(),
        )
        is not None
    )

    # A decoy, so SQLite's rowid counter does not hand the recreated type the
    # id it just freed — which is not what a real install does, and would make
    # this test pass for the wrong reason.
    await type_service.create_type(
        db, key="other", label="Other", settings=settings, fields_raw=fields
    )
    await db.delete(gone)
    await db.flush()
    fresh = await type_service.create_type(
        db, key="note", label="Note", settings=settings, fields_raw=fields
    )
    assert fresh.id != gone.id and fresh.version == 1
    assert (
        reused_report(
            fresh,
            current_version=fresh.version,
            fields_raw=list(fresh.fields or []),
            display_field=fresh.display_field,
            slug_field=fresh.slug_field,
            settings=settings,
            drop_keys=frozenset(),
        )
        is None
    )
