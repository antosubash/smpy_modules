"""Reading an import request: the bytes, the format, and the options.

Split from :mod:`sm_records.endpoints.api.io` for the 300-line cap, along the
seam that module's docstring already draws — everything here is HTTP-body
wrangling that happens *before* a service is called, and none of it knows what
a record is.

The two rules worth keeping in front of you:

* **The size ceiling is checked before anything is read.** A limit applied
  after ``json.loads`` has already allocated what it refuses.
* **The options come from the query string *and* the multipart form, the form
  winning.** Both, because both are how this is called: a browser posting a
  file dialog has a form and no query string, ``curl`` has a body that *is*
  the file and nowhere but the query string for an option.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from sm_records.contracts.io import ImportFormat
from sm_records.services.errors import ImportParseFailed, PayloadTooLarge, ValidationFailed
from sm_records.settings import RecordsSettings

__all__ = [
    "check_format",
    "enum_option",
    "flag_option",
    "guess_format",
    "read_upload",
    "text_option",
]


def check_format(raw: str) -> ImportFormat:
    try:
        return ImportFormat(raw)
    except ValueError as exc:
        raise ValidationFailed(
            f"format must be 'json' or 'csv', not {raw!r}",
            [{"field": "format", "message": f"unknown format {raw!r}"}],
        ) from exc


def guess_format(explicit: str | None, filename: str | None, content_type: str) -> ImportFormat:
    if explicit:
        return check_format(explicit)
    if filename and filename.lower().endswith(".csv"):
        return ImportFormat.CSV
    if filename and filename.lower().endswith(".json"):
        return ImportFormat.JSON
    if content_type.startswith(("text/csv", "application/csv")):
        return ImportFormat.CSV
    if content_type.startswith("application/json"):
        return ImportFormat.JSON
    raise ImportParseFailed(
        "cannot tell whether this is JSON or CSV: send ?format=, a .json/.csv filename, "
        "or Content-Type: application/json / text/csv"
    )


def _check_size(raw_length: int | None, settings: RecordsSettings) -> None:
    if raw_length is not None and raw_length > settings.max_import_bytes:
        raise PayloadTooLarge(
            f"the uploaded file is {raw_length} bytes, over the "
            f"{settings.max_import_bytes}-byte limit"
        )


async def read_upload(request: Request, settings: RecordsSettings) -> tuple[bytes, str | None, Any]:
    """The bytes, the filename (if any) and the multipart form (if any).

    ``Content-Length`` is checked before anything is read — a ceiling applied
    after the body is in memory has already allocated what it refuses — and
    again against what arrived, since a chunked request carries no header.
    """
    declared = request.headers.get("content-length")
    _check_size(int(declared) if declared and declared.isdigit() else None, settings)
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or isinstance(upload, str):
            raise ImportParseFailed("multipart upload is missing its 'file' part")
        raw = await upload.read()
        _check_size(len(raw), settings)
        return raw, upload.filename, form
    raw = await request.body()
    _check_size(len(raw), settings)
    return raw, None, None


def text_option(form: Any, name: str, fallback: str) -> str:
    value = None if form is None else form.get(name)
    return fallback if value is None or isinstance(value, bytes) else str(value)


def flag_option(form: Any, name: str, fallback: bool) -> bool:
    value = None if form is None else form.get(name)
    return fallback if value is None else str(value).strip().lower() in ("true", "1", "yes", "on")


def enum_option(factory: Any, raw: str, field: str) -> Any:
    try:
        return factory(raw)
    except ValueError as exc:
        raise ValidationFailed(
            f"{field} does not accept {raw!r}",
            [{"field": field, "message": f"unknown {field} {raw!r}"}],
        ) from exc
