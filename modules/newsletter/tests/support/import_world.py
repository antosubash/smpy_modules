"""A list, a queued import staged from fixture CSVs, and what the apply tests read back.

Builds on ``tests.imports.world`` (staging's helpers): ``queued`` stages and queues an export,
``run_all`` drives the runner to ``done``, and the readers look at records' and newsletter's
tables directly (test-only).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from simple_module_db import finalize_session
from sm_newsletter.core.suppression import suppress, suppressed
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.imports import runner
from sm_newsletter.imports.apply import BatchResult, apply_batch
from sm_newsletter.imports.service import queue_apply
from sm_newsletter.models import ImportEntry, ImportJob, Suppression
from sm_records.contracts.newsletter_import import importable_fields
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope as records_scope
from sm_records.models import tables_for
from sm_records.records.services import types as type_service
from sqlalchemy import func, select, update

from tests.imports.world import NOW, job_of, rows_of, staged, upload

job_row = job_of

SUB = "subscribed_members_export.csv"
UNSUB = "unsubscribed_members_export.csv"
CLEAN = "cleaned_members_export.csv"
SETTINGS = RecordsSettings()

__all__ = [
    "CLEAN",
    "NOW",
    "SETTINGS",
    "SUB",
    "UNSUB",
    "apply_now",
    "counts",
    "export",
    "job_row",
    "list_shape",
    "outcomes",
    "people",
    "pinned",
    "queue",
    "queued",
    "records_of",
    "run",
    "run_all",
    "set_job",
    "set_rows",
    "snapshot",
    "staged_count",
    "staged_outcomes",
    "suppress_at",
    "suppressed_of",
    "suppression_rows",
    "tag_choices",
]


def pinned(now: datetime = NOW) -> Callable[[], datetime]:
    """A clock that never moves."""
    return lambda: now


async def queue(state: Any, job_id: int, tenant: str = "default") -> None:
    """``staged``/``failed`` to ``queued`` through the service."""
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            job = (await s.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one()
            await queue_apply(s, tenant_id=tenant, job=job)
            await finalize_session(s)


async def queued(
    state: Any, *files: Any, tenant: str = "default", mapping: dict | None = None
) -> int:
    """Stage ``files`` on list ``news``, optionally replace the suggested mapping, queue it."""
    job_id = await staged(state, *files, tenant=tenant)
    if mapping is not None:
        await set_job(state, job_id, tenant=tenant, mapping=mapping)
    await queue(state, job_id, tenant)
    return job_id


async def set_job(state: Any, job_id: int, *, tenant: str = "default", **values: Any) -> None:
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            await s.execute(
                update(ImportJob)
                .where(ImportJob.id == job_id, ImportJob.tenant_id == tenant)
                .values(**values)
            )
            await s.commit()


async def set_rows(state: Any, job_id: int, *, tenant: str = "default", **values: Any) -> None:
    """Rewrite every staged row of the import (test-only)."""
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            await s.execute(
                update(ImportEntry)
                .where(ImportEntry.import_id == job_id, ImportEntry.tenant_id == tenant)
                .values(**values)
            )
            await s.commit()


async def run(
    factory: Callable[[], Any],
    job_id: int,
    *,
    tenant: str = "default",
    clock: Callable[[], datetime] | None = None,
    slice_seconds: float = 60,
) -> str:
    return await runner.run_import_async(
        factory,
        tenant_id=tenant,
        import_id=job_id,
        records_settings=SETTINGS,
        clock=clock or pinned(),
        slice_seconds=slice_seconds,
    )


async def run_all(factory: Callable[[], Any], job_id: int, *, tenant: str = "default", **kw: Any):
    """Slices until ``done``; every result seen."""
    seen = []
    for _ in range(1000):
        seen.append(await run(factory, job_id, tenant=tenant, **kw))
        if seen[-1] != "more":
            return seen
    raise AssertionError("the import never finished")


async def records_of(state: Any, tenant: str = "default", key: str = "news") -> dict[str, Any]:
    """Address -> record of list ``key``, trash included."""
    with records_scope(tenant):
        async with state.session_factory() as s:
            rtype = await type_service.get_type(s, key)
            table = tables_for(rtype).record
            stmt = select(table).where(table.tenant_id == tenant, table.type_id == rtype.id)
            rows = (await s.execute(stmt.execution_options(include_deleted=True))).scalars()
            return {r.data["sm_email"]: r for r in rows}


async def suppression_rows(state: Any, tenant: str = "default") -> list[tuple]:
    """``(email_hash, reason, list_type_key, source, created_at)`` of the tenant, sorted."""
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            rows = (
                await s.execute(select(Suppression).where(Suppression.tenant_id == tenant))
            ).scalars()
            return sorted(
                (r.email_hash, r.reason, r.list_type_key, r.source, r.created_at) for r in rows
            )


async def apply_now(state: Any, job_id: int, tenant: str = "default") -> BatchResult:
    """``apply_batch`` over every staged row, committed."""
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            job = (await s.execute(select(ImportJob).where(ImportJob.id == job_id))).scalar_one()
            stmt = select(ImportEntry).where(ImportEntry.import_id == job_id)
            rows = list((await s.execute(stmt.order_by(ImportEntry.seq))).scalars())
            targets = await importable_fields(s, tenant_id=tenant, type_key=job.list_type_key)
            result = await apply_batch(
                s,
                tenant_id=tenant,
                job=job,
                rows=rows,
                targets=targets,
                records_settings=SETTINGS,
                now=NOW,
            )
            await finalize_session(s)
            return result


async def outcomes(state, job_id: int, tenant: str = "default") -> dict[str, str | None]:
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            stmt = select(ImportEntry).where(ImportEntry.import_id == job_id)
            return {r.email: r.outcome for r in (await s.execute(stmt)).scalars()}


async def suppressed_of(state, emails, tenant: str = "default") -> set[str]:
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            return await suppressed(s, tenant_id=tenant, emails=emails)


async def suppress_at(state, email, reason, key="", tenant="default", at=NOW) -> None:
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            await suppress(
                s,
                tenant_id=tenant,
                email=email,
                reason=reason,
                source="admin",
                list_type_key=key,
                now=at,
            )
            await finalize_session(s)


async def tag_choices(state: Any) -> dict[str, str]:
    """Value -> label of list ``news``'s ``tags`` choices, indexed field or not."""
    return dict((await list_shape(state))[1])


def people(prefix: str, n: int, tags: str = "") -> list[list[str]]:
    return [[f"{prefix}{i}@example.org", f"N{i}", "", tags] for i in range(n)]


async def export(state, *, subs: int = 3, unsubs: int = 2, cleaned: int = 1) -> int:
    return await queued(
        state,
        upload(SUB, people("s", subs, "VIP")),
        upload(UNSUB, people("u", unsubs)),
        upload(CLEAN, people("c", cleaned)),
    )


async def staged_count(state, jid, tenant="default") -> int:
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            stmt = select(func.count()).select_from(ImportEntry)
            return (await s.execute(stmt.where(ImportEntry.import_id == jid))).scalar_one()


async def staged_outcomes(state, jid) -> list[str | None]:
    return [r.outcome for r in await rows_of(state, jid)]


def counts(job: ImportJob) -> tuple[int, ...]:
    return (job.created, job.updated, job.skipped, job.suppressed, job.failed)


async def snapshot(state, jid) -> tuple:
    records = {e: (r.uuid, r.version, dict(r.data)) for e, r in (await records_of(state)).items()}
    job = await job_row(state, jid)
    return (
        records,
        await suppression_rows(state),
        await staged_count(state, jid),
        job.model_dump(),
        await list_shape(state),
    )


async def list_shape(state: Any, tenant: str = "default", key: str = "news") -> tuple:
    """The list type's version and its ``tags`` choices: what a tags-step write changes."""
    with records_scope(tenant):
        async with state.session_factory() as s:
            rtype = await type_service.get_type(s, key)
            tags = next((f for f in rtype.fields or [] if f.get("key") == "tags"), {})
            choices = (tags.get("options") or {}).get("choices") or []
            return rtype.version, [(c["value"], c.get("label")) for c in choices]
