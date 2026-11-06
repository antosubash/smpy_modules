"""A records list, an upload and a staged import, for the staging, mapping and service tests."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.imports.archive import sources
from sm_newsletter.imports.staging import stage
from sm_newsletter.models import ImportEntry, ImportJob
from sqlalchemy import select

from tests.imports.fixtures import csv_bytes
from tests.support.records_seed import TAGS

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
HEAD = ["Email Address", "First Name", "Last Name", "TAGS"]
FIELDS = [
    {"key": "first_name", "type": "text", "label": "First name"},
    {"key": "last_name", "type": "text", "label": "Last name"},
    TAGS,
]


def upload(name: str, rows: list[list[str]], headers: list[str] | None = None, **kw: Any):
    return name, io.BytesIO(csv_bytes(headers or HEAD, rows, **kw))


async def staged(state: Any, *files: tuple[str, io.BytesIO], tenant: str = "default") -> int:
    """Stage ``files`` on list ``news`` and commit; the job id."""
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            job = await stage(
                s,
                tenant_id=tenant,
                list_type_key="news",
                sources=sources(list(files)),
                created_by="u",
                now=NOW,
            )
            await s.commit()
            return job.id


async def job_of(state: Any, job_id: int, tenant: str = "default") -> ImportJob:
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            return (await s.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one()


async def rows_of(state: Any, job_id: int, tenant: str = "default") -> list[ImportEntry]:
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            stmt = (
                select(ImportEntry).where(ImportEntry.import_id == job_id).order_by(ImportEntry.seq)
            )
            return list((await s.execute(stmt)).scalars())
