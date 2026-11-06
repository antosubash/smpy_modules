"""The import job and its staged rows: defaults, one row per address, cascade."""

from __future__ import annotations

import pytest
from sm_newsletter.models import ImportEntry, ImportJob
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError


async def _job(db) -> ImportJob:
    job = ImportJob(list_type_key="news", status="staged")
    db.add(job)
    await db.flush()
    return job


def _row(job: ImportJob, email_hash: str = "a" * 64) -> ImportEntry:
    return ImportEntry(
        import_id=job.id,
        seq=1,
        file_index=0,
        line=2,
        kind="subscribed",
        email="a@example.com",
        email_hash=email_hash,
    )


async def test_import_job_defaults(db):
    job = await _job(db)
    assert job.id > 0
    assert job.tenant_id == "default"
    assert job.status == "staged"
    assert (job.files, job.columns, job.mapping, job.tags_found, job.errors) == ([], [], {}, [], [])
    for name in (
        "total",
        "duplicates",
        "invalid",
        "processed",
        "created",
        "updated",
        "skipped",
        "suppressed",
        "failed",
        "errors_total",
    ):
        assert getattr(job, name) == 0, name
    assert job.tags_added is False
    assert job.error_code is None
    assert job.lease_owner is None and job.lease_until is None
    assert job.started_at is None and job.finished_at is None
    assert job.created_at is not None


async def test_import_row_unique_per_import_and_hash(db):
    first, second = await _job(db), await _job(db)
    db.add(_row(first))
    await db.flush()
    db.add(_row(second))
    await db.flush()  # the same address in another import is fine
    entry = _row(first)
    assert entry.outcome is None and entry.fields == {} and entry.tags == []
    async with db.begin_nested():
        db.add(entry)
        with pytest.raises(IntegrityError):
            await db.flush()


async def test_import_rows_cascade_with_job(db):
    job = await _job(db)
    db.add(_row(job))
    await db.flush()
    await db.delete(job)
    await db.flush()
    count = await db.scalar(select(func.count()).select_from(ImportEntry))
    assert count == 0
