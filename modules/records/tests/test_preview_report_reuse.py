"""A finished schema-preview report belongs to a ``type_id``, never to a
``type_key``, so a type deleted and recreated under one reuses nothing.
"""

from __future__ import annotations

import pytest
from sm_records.schema.changes import DryRunReport, SchemaDiff
from sm_records.services import preview_jobs
from sm_records.services import types as type_service
from sm_records.services._preview import reused_report
from sm_records.tenancy import DEFAULT_TENANT

from tests.field_builders import text

# ---------------------------------------------------------------------------
# a preview report is reused by type_id
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
        tenant_id=DEFAULT_TENANT,
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
