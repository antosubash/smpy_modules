"""Record Type CRUD endpoints — the schema half of the JSON API.

Mounted directly on ``ROUTE_PREFIX_API`` (``/api/records``), not under a
``/types`` sub-router with its own prefix: the paths below already spell
``/types`` and ``/types/{key}`` themselves, matching the contract in the
implementation plan exactly.
"""

from __future__ import annotations

from functools import partial

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.contracts.schema_change import (
    TypeRestoreRequest,
    TypeRevisionListResponse,
    type_revision_read,
)
from sm_records.contracts.schemas import (
    TypeCreate,
    TypeListResponse,
    TypeRead,
    TypeUpdate,
    type_read,
)
from sm_records.deferred import defer
from sm_records.deps import (
    actor,
    caller_roles,
    check_type_roles,
    get_settings,
    load_schema_type,
    load_type,
    request_db,
    require_manage_types,
    require_view,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.menu import affects_menu, mark_dirty
from sm_records.models import RecordType
from sm_records.services import _orphaned, reindex_runner, schema_change
from sm_records.services import revisions as revision_service
from sm_records.services import types as type_service
from sm_records.services._common import role_blocked
from sm_records.services.errors import ValidationFailed
from sm_records.settings import RecordsSettings

router = APIRouter(route_class=RecordsErrorRoute)


def _defer_reindex(request: Request, rtype: RecordType, settings: RecordsSettings) -> None:
    """§8.9: the reindex runs out of request, on its own session
    (``request.app.state.sm.db`` rather than the request's — see
    :mod:`sm_records.services.reindex_runner`).

    :func:`sm_records.deferred.defer`, *not* FastAPI's background tasks. Such a
    task runs inside the route's dependency teardown, so the request's session
    still holds its transaction while the rebuild wants one: on SQLite a
    deadlock the driver ends with ``database is locked``, and on any backend a
    rebuild reading the schema row as it was before the change it was
    scheduled for. :mod:`sm_records.deferred` explains the ordering.

    ``rtype.id`` is read here rather than inside the job: by the time the job
    runs the session that loaded the row is closed.
    """
    defer(
        request,
        partial(reindex_runner.schedule, request.app.state.sm.db, rtype.id, settings),
    )


def _schedule_reindex_if_pending(
    request: Request, rtype: RecordType, settings: RecordsSettings
) -> None:
    """Deferred whenever the write that just happened left something in
    ``reindex_pending`` — never unconditionally, or an edit that changed
    nothing indexable would queue a no-op job on every save."""
    if rtype.reindex_pending:
        _defer_reindex(request, rtype, settings)


def _check_roles_for_discard(request: Request, rtype: RecordType, orphaned: str | None) -> None:
    """``orphaned="discard"`` is a bulk write over this type's records (§8.8),
    so it meets the same ``allowed_roles`` narrowing a single record write
    does — ``records.manage_types`` is a permission to change the schema, not
    a way around a type whose records the caller may not touch. Every other
    schema edit stays gated by ``records.manage_types`` alone: it writes the
    type row, never the records.
    """
    if orphaned == _orphaned.DISCARD:
        check_type_roles(request, rtype)


@router.get("/types", response_model=TypeListResponse, dependencies=[require_view])
async def list_types(request: Request, db: AsyncSession = Depends(request_db)) -> TypeListResponse:
    """Every type this caller may read records of. One whose ``allowed_roles``
    exclude them is *omitted* rather than listed-and-then-403: every screen
    this feeds links straight to the type's record list, which
    ``deps.load_allowed_type`` refuses (§10). Reading one type by key is a
    different question — see :func:`read_type`."""
    roles = caller_roles(request)
    rtypes = [
        rtype for rtype in await type_service.list_types(db) if not role_blocked(rtype, roles)
    ]
    items = [type_read(rtype, *await type_service.record_counts(db, rtype)) for rtype in rtypes]
    return TypeListResponse(items=items)


@router.post(
    "/types", response_model=TypeRead, status_code=201, dependencies=[require_manage_types]
)
async def create_type(
    body: TypeCreate,
    request: Request,
    db: AsyncSession = Depends(request_db),
    settings=Depends(get_settings),
    who: str | None = Depends(actor),
) -> TypeRead:
    rtype = await type_service.create_type(
        db,
        key=body.key,
        label=body.label,
        settings=settings,
        label_plural=body.label_plural,
        description=body.description,
        icon=body.icon,
        fields_raw=body.fields,
        display_field=body.display_field,
        slug_field=body.slug_field,
        is_public=body.is_public,
        show_in_menu=body.show_in_menu,
        translatable=body.translatable,
        allowed_roles=body.allowed_roles,
        collection=body.collection,
        actor=who,
    )
    if body.show_in_menu:
        mark_dirty(request.app)
    # A freshly created type holds no records, trashed or otherwise — skip
    # the queries rather than count a table it cannot yet appear in.
    return type_read(rtype, 0, 0)


@router.get("/types/{key}", response_model=TypeRead, dependencies=[require_view])
async def read_type(
    rtype: RecordType = Depends(load_schema_type), db: AsyncSession = Depends(request_db)
) -> TypeRead:
    """One type's definition, and how many records it holds.

    ``load_schema_type`` and not ``load_type``: ``records.manage_types``
    reads this whatever ``allowed_roles`` says — the README's one exception,
    and the same one the type editor makes — and everybody else meets the
    narrowing. The ``record_count``/``trashed_record_count`` on ``TypeRead``
    are why it cannot simply be ``records.view``: they are a live count of a
    type whose records, trash and referrers this caller is refused.
    """
    return type_read(rtype, *await type_service.record_counts(db, rtype))


@router.put("/types/{key}", response_model=TypeRead, dependencies=[require_manage_types])
async def update_type(
    body: TypeUpdate,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> TypeRead:
    # Only what the caller actually sent — ``exclude_unset`` and not merely
    # "not None", since ``None`` is a legitimate value for e.g. ``description``.
    # ``force``/``orphaned`` are read straight off ``body`` below: they are
    # §8.2/§8.8's retry knobs, not columns, so they never belong in ``changes``.
    _check_roles_for_discard(request, rtype, body.orphaned)
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version", "force", "orphaned"})
    # ``key`` is not a column ``update_type`` accepts, but it *is* a key
    # clients send back with the rest of the type they just read. Dropping it
    # silently (the SQLModel default before ``TypeUpdate`` declared it) let a
    # caller believe it had renamed a type and get a 200; a value that differs
    # from the path is refused instead, and one that matches is a no-op echo.
    sent_key = changes.pop("key", None)
    if sent_key is not None and sent_key != rtype.key:
        problem = "key is immutable — it is in URLs, the API and every relation target"
        raise ValidationFailed(problem, [{"field": "key", "message": problem}])
    if "fields" in changes:
        changes["fields_raw"] = changes.pop("fields")
    before = list(rtype.fields or [])
    updated = await type_service.update_type(
        db,
        rtype,
        expected_version=body.expected_version,
        settings=settings,
        actor=who,
        force=body.force,
        orphaned=body.orphaned,
        **changes,
    )
    # Only for a change that can move the sidebar — the marking is cheap, but
    # the read it schedules is a query, and ``fields`` edits are the common
    # case on this route and never touch navigation.
    if affects_menu(changes):
        mark_dirty(request.app)
    events.publish(request, events.type_changed(updated, before))
    _schedule_reindex_if_pending(request, updated, settings)
    return type_read(updated, *await type_service.record_counts(db, updated))


@router.delete("/types/{key}", status_code=204, dependencies=[require_manage_types])
async def delete_type(
    request: Request,
    confirm_record_count: int = Query(...),
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
) -> None:
    """``records.manage_types`` *and* the type's own ``allowed_roles``.

    Deleting a type purges every record it holds, trash included — the widest
    write in the module. A caller the list excludes is refused a single record
    write and has a cascade into this type downgraded to ``restrict``
    (``services._lifecycle._role_blocked``); letting the same caller destroy all
    of it was the one gap in that rule, not a deliberate exception.
    """
    check_type_roles(request, rtype)
    shown = rtype.show_in_menu
    key = rtype.key
    purged = await type_service.delete_type(db, rtype, confirm_record_count=confirm_record_count)
    # ``key`` before the call, the rows out of it: afterwards the type row is
    # gone, and ``RecordPurged`` is the one event nothing can be looked up for.
    events.publish(request, *events.type_deleted(key, purged))
    # Read before the delete: afterwards the row is gone and the attribute is
    # a question about an expired instance.
    if shown:
        mark_dirty(request.app)


@router.post("/types/{key}/reindex", status_code=202, dependencies=[require_manage_types])
async def reindex_type(
    request: Request,
    rtype: RecordType = Depends(load_type),
    settings: RecordsSettings = Depends(get_settings),
) -> dict[str, bool]:
    """Manually kick a stuck reindex (§8.9's health check names it — this is
    the fix). Schedules unconditionally, whether or not anything is actually
    pending: the runner is idempotent (``run_pending`` is a no-op with
    nothing to do), and an operator pressing this button already believes
    something is stuck, so a silent no-op here for "there's nothing pending
    any more" would look like the button did nothing.
    """
    _defer_reindex(request, rtype, settings)
    return {"scheduled": True}


@router.get(
    "/types/{key}/revisions", response_model=TypeRevisionListResponse, dependencies=[require_view]
)
async def list_type_revisions(
    rtype: RecordType = Depends(load_schema_type), db: AsyncSession = Depends(request_db)
) -> TypeRevisionListResponse:
    """Every historical definition of this type — ``load_schema_type``, the
    same gate :func:`read_type` applies: the history of a schema is the
    schema, one version at a time."""
    revisions = await revision_service.list_type_revisions(db, rtype)
    return TypeRevisionListResponse(items=[type_revision_read(r) for r in revisions])


@router.post(
    "/types/{key}/revisions/{version}/restore",
    response_model=TypeRead,
    dependencies=[require_manage_types],
)
async def restore_type_revision(
    version: int,
    body: TypeRestoreRequest,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> TypeRead:
    """A schema rollback goes through :func:`schema_change.rollback`, which is
    :func:`schema_change.apply` under a new name (§8.6) — same 409 shapes as
    ``PUT``, mapped by the same ``RecordsErrorRoute``, and the same
    reindex-scheduling rule below it."""
    _check_roles_for_discard(request, rtype, body.orphaned)
    before = list(rtype.fields or [])
    updated, _ = await schema_change.rollback(
        db,
        rtype,
        to_version=version,
        expected_version=body.expected_version,
        settings=settings,
        actor=who,
        force=body.force,
        orphaned=body.orphaned,
    )
    events.publish(request, events.type_changed(updated, before))
    _schedule_reindex_if_pending(request, updated, settings)
    return type_read(updated, *await type_service.record_counts(db, updated))
