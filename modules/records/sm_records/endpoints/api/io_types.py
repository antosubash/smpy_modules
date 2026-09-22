"""Import and export of a **type definition** — the schema, not the documents.

Split from :mod:`sm_records.endpoints.api.io` for the 300-line cap, along the
seam that module's own docstring draws between "records in bulk" and "type
definitions". Nothing here touches a record: ``mode="update"`` hands the
definition to ``services.types.update_type``, which is the schema editor's own
call, so importing a definition onto a populated type is classified, dry-run
and refused exactly as editing it by hand is.

Mounted beside ``io.router``; the paths are unchanged.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.contracts.io import TypeExport, TypeImportRequest, type_export
from sm_records.contracts.schemas import TypeRead, type_read
from sm_records.deps import (
    actor,
    check_type_roles,
    get_settings,
    load_schema_type,
    request_db,
    require_manage_types,
    require_view,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.endpoints.api._responses import IMPORT, responses
from sm_records.endpoints.api.types import _check_roles_for_discard, _schedule_reindex_if_pending
from sm_records.menu import affects_menu, mark_dirty
from sm_records.models import RecordType
from sm_records.services import types as type_service
from sm_records.services.errors import ValidationFailed
from sm_records.settings import RecordsSettings

router = APIRouter(route_class=RecordsErrorRoute, responses=responses(*IMPORT))

_UPDATE = "update"


@router.get("/types/{key}/export", response_model=TypeExport, dependencies=[require_view])
async def export_type(rtype: RecordType = Depends(load_schema_type)) -> TypeExport:
    """The type definition alone, in the shape ``POST /types/import`` takes.

    ``load_schema_type``, which is what ``GET /types/{key}`` takes: this is
    the same definition — ``allowed_roles`` included — by another route, so
    it cannot be reachable where that one is not. A ``records.manage_types``
    holder reads it whatever the narrowing says; a caller the type excludes
    gets the 403 every other surface of that type gives them.
    """
    return type_export(rtype)


def _update_changes(request: Request, rtype: RecordType, body: TypeImportRequest) -> dict[str, Any]:
    """The columns a ``mode=update`` import writes — what the body actually sent.

    ``exclude_unset``, exactly as ``PUT /types/{key}`` builds its change set
    (``endpoints/api/types.py``), and for the same reason: a key the caller did
    not send is not a key they asked to change. Passing every attribute of
    ``TypeImportRequest`` instead wrote the *class defaults* over the stored
    row, so a definition that simply did not mention ``allowed_roles``,
    ``is_public`` or ``translatable`` cleared all three — a narrowed type
    silently widened and a public one silently unpublished by a routine
    "import this definition".

    ``allowed_roles`` then carries one rule of its own, because an export
    carries *every* field and a file from another install may name a list this
    one never agreed to: sending a list that differs from the stored one costs
    the same ``check_type_roles`` a record write does. Re-importing this
    install's own export sends the list it already has and is unaffected;
    widening a narrowing the caller is outside of stays where the README puts
    it — on the schema editor and its ``PUT``, where it is what the caller
    asked for rather than a side effect of a file.

    ``key`` is dropped rather than refused: it is the path here — it is what
    resolved ``rtype`` three lines up — so it cannot disagree with itself.

    ``collection`` stays in the change set and is handled by ``update_type``'s
    own ``_check_collection_unchanged``: an echo of the stored value is
    dropped, a *different* one is the 409 ``PUT /types/{key}`` gives. A
    collection is assigned at creation and never after, and a file must not be
    able to ask for a move silently.
    """
    changes = body.model_dump(
        exclude_unset=True,
        exclude={"mode", "expected_version", "force", "orphaned", "key"},
    )
    sent_roles = changes.get("allowed_roles")
    if sent_roles is not None and sorted(sent_roles) != sorted(rtype.allowed_roles or []):
        check_type_roles(request, rtype)
    if "fields" in changes:
        changes["fields_raw"] = changes.pop("fields")
    return changes


@router.post("/types/import", response_model=TypeRead, dependencies=[require_manage_types])
async def import_type(
    body: TypeImportRequest,
    request: Request,
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> TypeRead:
    """Create a type from a definition, or update one through the §8 pipeline.

    ``mode="update"`` goes through ``services.types.update_type`` — the schema
    editor's own call — so importing a definition onto a populated type is
    classified, dry-run and refused with a report exactly as editing it by
    hand is, and answers a refusal with the same ``force``/``orphaned``.
    Writing ``fields`` here would be a second schema path with none of §8
    behind it, which is the data loss §8 exists for.
    """
    if body.mode != _UPDATE:
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
            translatable=body.translatable,
            show_in_menu=body.show_in_menu,
            allowed_roles=body.allowed_roles,
            collection=body.collection,
            actor=who,
        )
        if body.show_in_menu:
            mark_dirty(request.app)
        return type_read(rtype, 0, 0)

    if body.expected_version is None:
        raise ValidationFailed(
            "mode=update needs the expected_version of the type it is replacing",
            [{"field": "expected_version", "message": "required when mode=update"}],
        )
    rtype = await type_service.get_type(db, body.key)
    _check_roles_for_discard(request, rtype, body.orphaned)
    changes = _update_changes(request, rtype, body)
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
    # Same rule as ``PUT /types/{key}``: an imported definition that renames a
    # type, re-icons it, narrows its roles or flips ``show_in_menu`` has moved
    # the sidebar, and nothing else here has.
    if affects_menu(changes):
        mark_dirty(request.app)
    events.publish(request, events.type_changed(updated, before))
    _schedule_reindex_if_pending(request, updated, settings)
    return type_read(updated, *await type_service.record_counts(db, updated))
