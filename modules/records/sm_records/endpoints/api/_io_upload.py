"""Reading an import request: the bytes, the format, and the options.

Split from :mod:`sm_records.endpoints.api.io` for the 300-line cap, along the
seam that module's docstring already draws — everything here is HTTP-body
wrangling that happens *before* a service is called, and none of it knows what
a record is.

The two rules worth keeping in front of you:

* **The size ceiling is applied while the body is read, not after.**
  ``Content-Length`` is checked before anything is read at all, and a request
  that declares none — a chunked upload, which is what an HTTP client sends
  when it streams a file — is counted byte by byte and refused the moment the
  running total passes the ceiling. A limit applied after ``json.loads`` (or
  after ``await request.body()``) has already allocated what it refuses: the
  413 arrived, and 64 MB had been read to produce it.
* **The options come from the query string *and* the multipart form, the form
  winning.** Both, because both are how this is called: a browser posting a
  file dialog has a form and no query string, ``curl`` has a body that *is*
  the file and nowhere but the query string for an option.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request
from starlette.formparsers import MultiPartException

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


MAX_FORM_FIELDS = 32
"""How many non-file parts a multipart import may carry. The options are six
(``format``, ``mode``, ``dry_run``, ``on_error``, ``match_by``, ``force``) and
every browser form here sends a subset; the headroom is for a client that
repeats one. Starlette's own default is 1 000, each of which is a parsed and
retained ``str``."""

MAX_FORM_FILES = 4
"""How many file parts it may carry. One is read (``file``); the rest are
spooled to disk by the parser before anything here sees them, which is what
this bounds."""


def _check_size(raw_length: int | None, settings: RecordsSettings) -> None:
    if raw_length is not None and raw_length > settings.max_import_bytes:
        raise PayloadTooLarge(
            f"the uploaded file is {raw_length} bytes, over the "
            f"{settings.max_import_bytes}-byte limit"
        )


def _counting_receive(request: Request, limit: int) -> Callable[[], Any]:
    """``request.receive``, refusing at the first byte past ``limit``.

    The ASGI channel and not the parsed body, because that is the only layer
    both paths share: the raw branch buffers with ``Request.body`` and the
    multipart branch hands the same channel to Starlette's parser, which
    spools each part to a ``SpooledTemporaryFile`` — a ceiling checked after
    either has finished is a ceiling that has already paid for what it
    refuses. A wrapped ``receive`` counts what actually arrived, which is the
    one number a request without ``Content-Length`` cannot lie about.
    """
    seen = 0

    async def receive() -> Any:
        nonlocal seen
        message = await request.receive()
        if message.get("type") == "http.request":
            seen += len(message.get("body", b"") or b"")
            if seen > limit:
                raise PayloadTooLarge(f"the uploaded file is over the {limit}-byte limit")
        return message

    return receive


async def read_upload(request: Request, settings: RecordsSettings) -> tuple[bytes, str | None, Any]:
    """The bytes, the filename (if any) and the multipart form (if any).

    ``Content-Length`` is refused before a byte is read, and the body itself
    is read through :func:`_counting_receive` so a request that declares no
    length — every chunked upload — is refused at the first byte over the
    ceiling rather than after the whole of it is in memory.

    The multipart branch additionally bounds what the *parser* will build:
    ``max_part_size`` is the same ceiling (a single part cannot exceed a body
    that is already capped, so this can only ever agree with the count above),
    and ``max_files``/``max_fields`` cap the number of parts, which
    ``Content-Length`` does not — a small body can carry a thousand of them.
    A refusal from the parser is this module's own 400, not the 500 an
    unhandled ``MultiPartException`` would be.
    """
    declared = request.headers.get("content-length")
    _check_size(int(declared) if declared and declared.isdigit() else None, settings)
    limit = settings.max_import_bytes
    capped = Request(request.scope, _counting_receive(request, limit))
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        try:
            form = await capped.form(
                max_part_size=max(limit, 1),
                max_files=MAX_FORM_FILES,
                max_fields=MAX_FORM_FIELDS,
            )
        except MultiPartException as exc:
            raise ImportParseFailed(f"the multipart upload could not be read: {exc}") from exc
        upload = form.get("file")
        if upload is None or isinstance(upload, str):
            raise ImportParseFailed("multipart upload is missing its 'file' part")
        raw = await upload.read()
        _check_size(len(raw), settings)
        return raw, upload.filename, form
    raw = await capped.body()
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
