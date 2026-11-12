"""web endpoints api _type_writes helpers."""

from __future__ import annotations

from functools import partial
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.io import TypeImportRequest
from sm_records.contracts.schemas import TypeCreate, TypeRead, TypeUpdate, type_read
from sm_records.core import events
from sm_records.core.settings import RecordsSettings
from sm_records.models import RecordType
from sm_records.records.deferred import defer
from sm_records.records.services import reindex_runner
from sm_records.records.services import types as type_service
from sm_records.records.services.schema_changes import _orphaned
from sm_records.web.deps import check_type_roles
from sm_records.web.menu import affects_menu, mark_dirty


def _defer_reindex(request: Request, rtype: RecordType, settings: RecordsSettings) -> None:
    """§8.9: the reindex runs out of request, on its own session
    (``request.app.state.sm.db`` rather than the request's — see
    :mod:`sm_records.records.services.reindex_runner`).

    :func:`sm_records.records.deferred.defer`, *not* FastAPI's background tasks. Such a
    task runs inside the route's dependency teardown, so the request's session
    still holds its transaction while the rebuild wants one: on SQLite a
    deadlock the driver ends with ``database is locked``, and on any backend a
    rebuild reading the schema row as it was before the change it was
    scheduled for. :mod:`sm_records.records.deferred` explains the ordering.

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


async def create_from(
    request: Request,
    db: AsyncSession,
    body: TypeCreate | TypeImportRequest,
    settings: RecordsSettings,
    who: str | None,
) -> TypeRead:
    """Create a type from a body — ``POST /types``, and an import's create mode."""
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
        public_submissions=body.public_submissions,
        actor=who,
    )
    # Every new type is a new ``records.type.<key>`` in the role editor,
    # whether or not it asked for a sidebar entry.
    mark_dirty(request.app)
    # A freshly created type holds no records, trashed or otherwise — skip
    # the queries rather than count a table it cannot yet appear in.
    return type_read(rtype, 0, 0, 0)


async def type_written(
    request: Request,
    db: AsyncSession,
    updated: RecordType,
    before: list,
    settings: RecordsSettings,
) -> TypeRead:
    """What every edit of a type row does last: the event, the deferred
    reindex if one is pending, and the fresh ``TypeRead``.

    The one event still emitted from an endpoint: ``update_type``,
    ``schema_change.apply`` and ``schema_change.rollback`` all end here, and no
    path outside a request writes a type's schema. It goes through the same
    ``on_commit`` queue as the rest (:mod:`sm_records.core.events`), so it is
    published when the request commits — still ahead of the reindex, which
    stays on :mod:`sm_records.records.deferred`."""
    events.emit(db, events.type_changed(updated, before))
    _schedule_reindex_if_pending(request, updated, settings)
    return type_read(updated, *await type_service.record_counts(db, updated))


async def apply_update(
    request: Request,
    db: AsyncSession,
    rtype: RecordType,
    body: TypeUpdate | TypeImportRequest,
    changes: dict[str, Any],
    settings: RecordsSettings,
    who: str | None,
) -> TypeRead:
    """``update_type`` with ``changes`` — ``PUT /types/{key}``, and an
    import's update mode."""
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
    return await type_written(request, db, updated, before, settings)
