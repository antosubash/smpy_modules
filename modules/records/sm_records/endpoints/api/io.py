"""Import and export endpoints — records in bulk.

The **type definition** half (``/types/import``, ``/types/{key}/export``) lives
in :mod:`sm_records.endpoints.api.io_types`, split off for the 300-line cap
along the seam this docstring already drew: nothing there touches a record.

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

from sm_records import events
from sm_records.contracts.io import (
    ImportFormat,
    ImportMode,
    ImportReport,
    OnError,
)
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
from sm_records.endpoints.api._responses import IMPORT, responses
from sm_records.index.query import Filter, Sort, build_query
from sm_records.models import RecordType
from sm_records.services import export as export_service
from sm_records.services import import_ as import_service
from sm_records.services.errors import ImportParseFailed
from sm_records.settings import RecordsSettings

router = APIRouter(route_class=RecordsErrorRoute, responses=responses(*IMPORT))

_MEDIA = {ImportFormat.JSON: "application/json", ImportFormat.CSV: "text/csv; charset=utf-8"}

_EXPORT_200 = {
    200: {
        "description": (
            "The whole selection, streamed, as an attachment. `?format=json` is the "
            'export document (`{"type": …, "records": […]}`); `?format=csv` is the '
            "header-driven table."
        ),
        "content": {"application/json": {}, "text/csv": {}},
    }
}
"""Declared by hand because the handler returns a ``StreamingResponse``: the
schema said ``application/json`` for a route that also serves ``text/csv``,
which is exactly the sort of thing a generated client believes."""


@router.get(
    "/types/{key}/records/export",
    dependencies=[require_view],
    response_model=None,
    responses=_EXPORT_200,
)
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
    # One event per row that wrote, not one per file: a subscriber acts on
    # records, and an import is many ordinary writes (``_import_rows.write_row``
    # goes through ``create_record``/``update_record`` for exactly that reason).
    # A dry run fills nothing, because it wrote nothing.
    written: list[Any] = []
    report = await import_service.import_records(
        db, rtype, text, fmt=chosen, options=options, settings=settings, actor=who, written=written
    )
    events.publish(request, *events.imported(rtype, written))
    return report
