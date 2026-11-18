"""``/api/events/imports``: upload an ``.ics``, preview it, apply it, discard it.

The parent router binds the tenant (first) and the CSRF check; every route here needs
``events.view`` **and** ``events.manage``. The calendar must be one the caller may write events
in (404 for one they cannot see, 403 for one they can only see). The file is read in chunks and
stops at the stored cap, clamped (``import_max_bytes``); parsing and applying are the worker's
(:mod:`sm_events.feeds.importing.runner`), started here only after the row is committed. A
response never carries the file, an item's payload or the importer's permissions.

**Who may see an import** (the plan is silent; the module's ruling): **its creator, and only
while they can still write events in its calendar.** Every route that names an import goes through
:func:`owned_import`, which answers 404, the same 404 a missing id gets, for another user's
import, another tenant's, and one whose calendar is trashed or no longer writable by the caller:
an integer id confirms nothing. The list is filtered the same way, in SQL. A creator who loses the
calendar loses the import too (the janitor deletes it). Previews carry titles, places and
descriptions from the file, so this is the privacy boundary.

**Apply** (``staged`` to ``queued``) records the caller's ``events.*`` permissions on the row (the
worker has no session to ask) and whether they may publish; publishing needs ``events.publish``
(403 ``publish_required``). It is one conditional ``UPDATE``, so applying twice is a 409
``import_state``, never two runs. **Discard** is for ``staged``, ``failed`` and ``done`` imports
only; one a worker holds is a 409.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from simple_module_core.resources import ResourcePrincipal
from simple_module_db import finalize_session
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import resource_principal
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import defer

from sm_events.core import constants
from sm_events.core.access import ACTION_WRITE_EVENTS, POLICY
from sm_events.core.access.rights import writable_calendar
from sm_events.core.clock import utcnow
from sm_events.core.errors import Forbidden, ImportState, NotFound, PublishRequired
from sm_events.core.tenancy import bound_tenant
from sm_events.feeds.importing import launch, staging
from sm_events.models import Calendar, EventImport, EventImportItem
from sm_events.web.endpoints.deps import get_settings, require_manage, require_view
from sm_events.web.schemas.imports import (
    ApplyIn,
    CalendarRef,
    ImportItemPage,
    ImportOut,
    ImportPage,
    import_out,
    item_out,
)

router = APIRouter(prefix="/imports", tags=["imports"], dependencies=[require_view, require_manage])

Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]
PageSize = Annotated[int, Query(ge=1, le=100)]
_FINISHED = ("staged", "failed", "done")


async def _calendars(db, ids: set[uuid.UUID]) -> dict[uuid.UUID, CalendarRef]:
    if not ids:
        return {}
    stmt = (
        select(Calendar.id, Calendar.name)
        .where(Calendar.tenant_id == bound_tenant(), Calendar.id.in_(ids))  # type: ignore[arg-type,attr-defined]
        .execution_options(include_deleted=True)
    )
    return {row.id: CalendarRef(id=row.id, name=row.name) for row in await db.execute(stmt)}


async def _row(db, import_id: int) -> EventImport:
    """The import in the bound tenant, whoever's it is: for :func:`owned_import` and the
    worker-side re-reads after a launch; never for a route's first look."""
    row = (
        await db.execute(
            select(EventImport)
            .options(defer(EventImport.source))  # never the raw upload (up to 20 MiB)
            .where(EventImport.tenant_id == bound_tenant(), EventImport.id == import_id)  # type: ignore[arg-type]
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound
    return row


async def _out(db, row: EventImport) -> ImportOut:
    found = await _calendars(db, {row.calendar_id})
    return import_out(row, found.get(row.calendar_id) or CalendarRef(id=row.calendar_id, name=""))


async def owned_import(import_id: int, who: Principal, db=Depends(get_db)) -> EventImport:
    """The import, if ``who`` created it and can still write events in its calendar; else a 404
    that is the missing-id 404."""
    row = await _row(db, import_id)
    if row.created_by != who.user_id:
        raise NotFound
    try:
        await writable_calendar(db, who, row.calendar_id)
    except (NotFound, Forbidden):
        raise NotFound from None
    return row


Owned = Annotated[EventImport, Depends(owned_import)]


def _mine(who: ResourcePrincipal):
    """The caller's own imports of calendars they can write now, as one SQL condition."""
    writable = POLICY.filter(who, ACTION_WRITE_EVENTS, select(Calendar.id))
    return (
        EventImport.tenant_id == bound_tenant(),
        EventImport.created_by == who.user_id,
        EventImport.calendar_id.in_(writable),  # type: ignore[attr-defined]
    )


@router.get("")
async def list_imports(
    who: Principal,
    db=Depends(get_db),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: PageSize = 20,
) -> ImportPage:
    where = _mine(who)
    total = (
        await db.execute(select(func.count()).select_from(EventImport).where(*where))  # type: ignore[arg-type]
    ).scalar_one()
    rows = list(
        (
            await db.execute(
                select(EventImport)
                .options(defer(EventImport.source))
                .where(*where)  # type: ignore[arg-type]
                .order_by(EventImport.id.desc())  # type: ignore[union-attr]
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )
    names = await _calendars(db, {r.calendar_id for r in rows})
    items = [
        import_out(r, names.get(r.calendar_id) or CalendarRef(id=r.calendar_id, name=""))
        for r in rows
    ]
    return ImportPage(items=items, total=total)


@router.post("", status_code=202)
async def upload(
    request: Request,
    who: Principal,
    calendar_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File()],
    db=Depends(get_db),
) -> ImportOut:
    limit = staging.effective_max_bytes(get_settings(request))
    try:
        data = await staging.read_upload(file, limit=limit)
    finally:
        await file.close()
    row = await staging.create_import(
        db,
        who,
        calendar_id=calendar_id,
        filename=file.filename or "",
        data=data,
        now=utcnow(),
    )
    import_id, tenant = row.id, bound_tenant()
    await finalize_session(db)  # committed before a worker (or the eager launch) looks for it
    await launch.launch(request.app, tenant_id=tenant, import_id=import_id)
    return await _out(db, await _row(db, import_id))


@router.get("/{import_id}")
async def get_import(row: Owned, db=Depends(get_db)) -> ImportOut:
    return await _out(db, row)


@router.get("/{import_id}/items")
async def list_items(
    row: Owned,
    db=Depends(get_db),
    verdict: Literal["new", "update", "unchanged", "skip"] | None = None,
    outcome: Literal["created", "updated", "unchanged", "skipped", "failed"] | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: PageSize = 50,
) -> ImportItemPage:
    where = [
        EventImportItem.tenant_id == bound_tenant(),
        EventImportItem.import_id == row.id,
    ]
    if verdict is not None:
        where.append(EventImportItem.verdict == verdict)
    if outcome is not None:
        where.append(EventImportItem.outcome == outcome)
    total = (
        await db.execute(select(func.count()).select_from(EventImportItem).where(*where))  # type: ignore[arg-type]
    ).scalar_one()
    rows = (
        await db.execute(
            select(EventImportItem)
            .where(*where)  # type: ignore[arg-type]
            .order_by(EventImportItem.seq)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars()
    items = [item_out(r) for r in rows]
    return ImportItemPage(items=items, total=total, page=page, page_size=page_size)


@router.post("/{import_id}/apply", status_code=202)
async def apply(
    row: Owned, body: ApplyIn, request: Request, who: Principal, db=Depends(get_db)
) -> ImportOut:
    import_id = row.id
    may_publish = who.has(constants.PERM_PUBLISH)
    if body.publish and not may_publish:
        raise PublishRequired
    table = EventImport.__table__
    moved = await db.execute(
        update(table)
        .where(
            table.c.id == import_id,
            table.c.tenant_id == bound_tenant(),
            table.c.status == "staged",
        )
        .values(
            status="queued",
            publish=body.publish,
            may_publish=may_publish,
            grants=staging.grants_of(who),
            rights_until=utcnow() + constants.IMPORT_GRANTS_TTL,
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    if moved.rowcount != 1:
        raise ImportState
    tenant = bound_tenant()
    await finalize_session(db)
    await launch.launch(request.app, tenant_id=tenant, import_id=import_id)
    return await _out(db, await _row(db, import_id))


@router.delete("/{import_id}", status_code=204)
async def discard(row: Owned, db=Depends(get_db)) -> Response:
    import_id = row.id
    items, table = EventImportItem.__table__, EventImport.__table__
    gone = await db.execute(
        delete(table)
        .where(
            table.c.id == import_id,
            table.c.tenant_id == bound_tenant(),
            table.c.status.in_(_FINISHED),
        )
        .execution_options(synchronize_session=False)
    )
    if gone.rowcount != 1:
        raise ImportState
    await db.execute(delete(items).where(items.c.import_id == import_id))
    return Response(status_code=204)
