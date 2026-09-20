"""Import and export endpoints — records in bulk, and type definitions.

Mounted **before** ``records.router`` in :mod:`sm_records.endpoints.api`:
Starlette matches in registration order, so ``/types/{key}/records/export``
after ``/types/{key}/records/{uuid}`` is a request for a record uuid'd
``"export"``.

The export is a ``StreamingResponse`` over a session of its own: its body is
produced *after* the handler returns, and when FastAPI unwinds a ``yield``
dependency is a version detail rather than a promise, so the generator opens
its own read-only session (``services.export``) — the escape hatch
``_errors.py`` uses. The request's session still resolves the type, so the
404 and the 403 happen before any body at all.

The import's knobs come from the query string *and* the multipart form, the
form winning — both, because both are how it is called: a browser posting a
file dialog has a form and no query string, ``curl`` has a body that *is* the
file and nowhere but the query string for an option.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.io import (
    ImportFormat,
    ImportMode,
    ImportReport,
    OnError,
    TypeExport,
    TypeImportRequest,
    type_export,
)
from sm_records.contracts.schemas import TypeRead, type_read
from sm_records.deps import (
    actor,
    check_type_roles,
    get_settings,
    load_allowed_type,
    load_type,
    parse_filters,
    parse_sorts,
    parse_trashed,
    request_db,
    require_edit,
    require_manage_types,
    require_view,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.endpoints.api._io_upload import (
    check_format,
    enum_option,
    flag_option,
    guess_format,
    read_upload,
    text_option,
)
from sm_records.endpoints.api.types import _check_roles_for_discard, _schedule_reindex_if_pending
from sm_records.index.query import Filter, Sort
from sm_records.models import RecordType
from sm_records.services import export as export_service
from sm_records.services import import_ as import_service
from sm_records.services import types as type_service
from sm_records.services.errors import ImportParseFailed, ValidationFailed
from sm_records.settings import RecordsSettings

router = APIRouter(route_class=RecordsErrorRoute)

_MEDIA = {ImportFormat.JSON: "application/json", ImportFormat.CSV: "text/csv; charset=utf-8"}
_UPDATE = "update"


@router.get("/types/{key}/records/export", dependencies=[require_view])
async def export_records(
    request: Request,
    rtype: RecordType = Depends(load_allowed_type),
    settings: RecordsSettings = Depends(get_settings),
    fmt: str = Query(default=ImportFormat.JSON.value, alias="format"),
    filters: list[Filter] = Depends(parse_filters),
    sorts: list[Sort] = Depends(parse_sorts),
    trashed: bool = Depends(parse_trashed),
) -> StreamingResponse:
    """Every record of the type, streamed.

    ``load_allowed_type`` — the list route's own dependency, because an export
    is a read of exactly what that route would return, narrowed by the type's
    ``allowed_roles`` (§10). ``?trashed=true`` costs ``records.edit`` for the
    same reason it does there: enumerating the trash is an editor's question.
    """
    chosen = check_format(fmt)
    factory = request.app.state.sm.db.session_factory
    stream = export_service.iter_json if chosen is ImportFormat.JSON else export_service.iter_csv
    filename = export_service.export_filename(rtype.key, chosen.value)
    return StreamingResponse(
        stream(
            factory,
            int(rtype.id or 0),
            settings=settings,
            filters=filters,
            sorts=sorts,
            trashed=trashed,
        ),
        media_type=_MEDIA[chosen],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/types/{key}/records/import", response_model=ImportReport, dependencies=[require_edit]
)
async def import_records(
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
    mode: str = Query(default=ImportMode.UPSERT.value),
    dry_run: bool = Query(default=True),
    on_error: str = Query(default=OnError.ABORT.value),
    match_by: str = Query(default="uuid"),
    force: bool = Query(default=False),
    fmt: str | None = Query(default=None, alias="format"),
) -> ImportReport:
    """Import a file of records. **Dry run unless ``dry_run=false``.**

    ``records.edit`` plus ``allowed_roles`` (§10), exactly what a single write
    costs — an import is one, many times over.
    """
    check_type_roles(request, rtype)
    raw, filename, form = await read_upload(request, settings)
    chosen = guess_format(
        text_option(form, "format", fmt or "") or None,
        filename,
        request.headers.get("content-type", ""),
    )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportParseFailed(f"the file is not valid UTF-8 (byte {exc.start})") from exc
    options = import_service.ImportOptions(
        mode=enum_option(ImportMode, text_option(form, "mode", mode), "mode"),
        dry_run=flag_option(form, "dry_run", dry_run),
        on_error=enum_option(OnError, text_option(form, "on_error", on_error), "on_error"),
        match_by=text_option(form, "match_by", match_by),
        force=flag_option(form, "force", force),
    )
    return await import_service.import_records(
        db, rtype, text, fmt=chosen, options=options, settings=settings, actor=who
    )


@router.get("/types/{key}/export", response_model=TypeExport, dependencies=[require_view])
async def export_type(rtype: RecordType = Depends(load_type)) -> TypeExport:
    """The type definition alone, in the shape ``POST /types/import`` takes.

    ``load_type`` and not ``load_allowed_type``: ``allowed_roles`` narrows a
    type's *records* (§10), and ``GET /types/{key}`` already serves the schema
    to anyone holding ``records.view``.
    """
    return type_export(rtype)


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
            allowed_roles=body.allowed_roles,
            actor=who,
        )
        return type_read(rtype, 0, 0)

    if body.expected_version is None:
        raise ValidationFailed(
            "mode=update needs the expected_version of the type it is replacing",
            [{"field": "expected_version", "message": "required when mode=update"}],
        )
    rtype = await type_service.get_type(db, body.key)
    _check_roles_for_discard(request, rtype, body.orphaned)
    updated = await type_service.update_type(
        db,
        rtype,
        expected_version=body.expected_version,
        settings=settings,
        actor=who,
        force=body.force,
        orphaned=body.orphaned,
        label=body.label,
        label_plural=body.label_plural,
        description=body.description,
        icon=body.icon,
        fields_raw=body.fields,
        display_field=body.display_field,
        slug_field=body.slug_field,
        is_public=body.is_public,
        translatable=body.translatable,
        allowed_roles=body.allowed_roles,
    )
    _schedule_reindex_if_pending(request, updated, settings)
    return type_read(updated, *await type_service.record_counts(db, updated))
