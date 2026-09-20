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

from typing import Any

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
    load_schema_type,
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
from sm_records.index.query import Filter, Sort, build_query
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

    **The query plan is resolved here, before the response exists.** A refused
    ``?filter=``/``?sort=`` — an unknown field, an unindexed one, one
    mid-reindex — is a ``QueryError``, and raised from inside the streaming
    body it arrives after ``http.response.start``: nothing can turn it into a
    status any more, so the caller downloaded a ``200 OK`` named
    ``post-2026-09-20.json`` holding a truncated JSON prefix and the server
    logged an unhandled exception. Building the same statement in the handler
    costs one throwaway ``Select`` and no database round trip, and puts the
    refusal back where ``RecordsErrorRoute`` maps it to the list's own 400
    (or 409, mid-reindex) with a JSON body and no headers sent.
    """
    chosen = check_format(fmt)
    build_query(rtype, list(rtype.fields or []), filters, sorts)
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
        **_update_changes(request, rtype, body),
    )
    _schedule_reindex_if_pending(request, updated, settings)
    return type_read(updated, *await type_service.record_counts(db, updated))
