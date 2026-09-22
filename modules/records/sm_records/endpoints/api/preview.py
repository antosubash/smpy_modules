"""``POST /types/{key}/schema/preview`` and its deferred half — §8.9, F10.

Split from :mod:`sm_records.endpoints.api.types` for the 300-line cap, along
a seam the endpoint grew when it stopped always being synchronous: everything
here is about *a dry run as an operation with a lifetime*, while ``types``
stays about the type row.

A dry run validates every record of the type, trash included, at roughly a
thousand records a second. Up to ``RecordsSettings.preview_sync_limit`` that
is a request and this answers ``200`` with the report; above it that is
minutes of HTTP with whatever proxy timeout that implies, so this answers
``202 {"job": ..., "status": "running"}`` and the caller polls
:func:`read_preview_job` for "checked N of M" and then the same report.

A draft preview writes nothing, which is what makes the 404 on an unknown job
harmless: the client's answer to it is to preview again. A ``rescan`` is the
exception — it scans the schema the records are stored against and records
what it finds on each record's ``invalid_since``
(:mod:`sm_records.services._invalid`) — and re-running one is idempotent, so
the answer to a 404 does not change.
"""

from __future__ import annotations

from functools import partial

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.schema_change import (
    SchemaPreviewJobRead,
    SchemaPreviewRead,
    SchemaPreviewRequest,
    schema_preview_job_read,
    schema_preview_read,
)
from sm_records.deferred import defer
from sm_records.deps import (
    get_settings,
    load_type,
    request_db,
    require_manage_types,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.endpoints.api._responses import TYPE_WRITE, responses
from sm_records.models import RecordType
from sm_records.services import preview_jobs, preview_runner, schema_change
from sm_records.services._common import record_count
from sm_records.services.errors import NotFound
from sm_records.services.schema_change import MISSING
from sm_records.settings import RecordsSettings

router = APIRouter(route_class=RecordsErrorRoute, responses=responses(*TYPE_WRITE))


@router.post(
    "/types/{key}/schema/preview",
    response_model=None,
    dependencies=[require_manage_types],
    responses={
        200: {
            "model": SchemaPreviewRead,
            "description": "The dry run, done inside the request.",
        },
        202: {
            "model": SchemaPreviewJobRead,
            "description": (
                "The type is over `preview_sync_limit`, so the scan runs out of request; "
                "poll `GET /types/{key}/schema/preview/{job}`."
            ),
        },
    },
)
async def preview_schema(
    body: SchemaPreviewRequest,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
) -> SchemaPreviewRead | JSONResponse:
    """Classifies and dry-runs; it changes no schema and no payload (§8.9).

    Under ``rescan`` it does write one thing: the ``invalid_since`` mark the
    scan found (``services._invalid``). That needs no ``try``/``except`` here
    — ``RecordsErrorRoute`` rolls the request's session back on every error
    path, which is the rule its module docstring states.

    ``exclude_unset`` is what lets a caller that only ever sends ``fields``
    (today's UI) reach :func:`schema_change.preview` without its
    ``display_field``/``slug_field`` arguments at all, rather than as an
    explicit ``None`` that would misread as "clear the pointer".

    Synchronous up to ``preview_sync_limit`` records and ``202`` above it
    (F10). The scan is ~1,000 records a second, so a big type is a minutes-
    long HTTP request for an answer a screen can show a progress bar for; the
    202 body is ``{"job": ..., "status": "running"}`` and the caller polls
    :func:`read_preview_job`. The count includes the trash, because the scan
    does (§8.9).

    ``rescan`` scans whatever the diff says, which is what "Check records"
    needs: it resends the *stored* fields, so the diff is empty and the report
    would otherwise short-circuit to ``failing=0`` — a clean bill of health
    for records nothing looked at. It is the only way to re-derive the
    worklist a forced restrictive change leaves behind. Both paths take it,
    and it is part of a deferred job's signature so a later *save* can never
    reuse a "Check records" report (``services.preview_jobs.fields_hash``).
    """
    sent = body.model_dump(exclude_unset=True)
    total = await record_count(db, rtype, include_deleted=True)
    if total <= settings.preview_sync_limit:
        diff, report = await schema_change.preview(
            db,
            rtype,
            body.fields,
            settings,
            display_field=sent.get("display_field", MISSING),
            slug_field=sent.get("slug_field", MISSING),
            rescan=body.rescan,
        )
        return schema_preview_read(diff, report)
    job = preview_jobs.start(
        type_key=rtype.key,
        type_id=rtype.id,
        type_version=rtype.version,
        signature=preview_jobs.fields_hash(
            body.fields,
            sent.get("display_field", rtype.display_field),
            sent.get("slug_field", rtype.slug_field),
            rescan=body.rescan,
        ),
        total=total,
        ttl_seconds=settings.preview_job_ttl_seconds,
    )
    defer(
        request,
        partial(
            preview_runner.run_preview_job,
            request.app.state.sm.db,
            job.id,
            rtype.id,
            body.fields,
            display_field=sent.get("display_field", MISSING),
            slug_field=sent.get("slug_field", MISSING),
            rescan=body.rescan,
            settings=settings,
        ),
    )
    return JSONResponse(status_code=202, content={"job": job.id, "status": job.status})


@router.get(
    "/types/{key}/schema/preview/{job}",
    response_model=SchemaPreviewJobRead,
    dependencies=[require_manage_types],
)
async def read_preview_job(
    job: str, rtype: RecordType = Depends(load_type)
) -> SchemaPreviewJobRead:
    """One deferred preview's progress, and its report once it is done.

    404 for a job this process does not hold — it finished long enough ago to
    be pruned, the worker restarted, or (on a multi-worker host) another
    worker ran it. The registry is deliberately in-process
    (:mod:`sm_records.services.preview_jobs`), and the client's answer to a
    404 is to preview again, which is safe because a preview writes nothing.

    The job is checked against the type in the path: a job id is a handle to
    a report about one type's records, and ``records.manage_types`` is
    type-agnostic, so serving job X under type Y would let a caller read a
    report they asked for under a URL that says otherwise.
    """
    found = preview_jobs.get(job)
    if found is None or found.type_key != rtype.key:
        raise NotFound(f"no schema preview job {job!r} for {rtype.key!r}")
    return schema_preview_job_read(found)


__all__ = ["router"]
