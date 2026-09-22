"""Turning an uploaded file into rows, before anything is validated or written.

The division of labour with :mod:`sm_records.services.import_` is strict and
worth keeping: **this module decides what the file says, and never what it
means.** A cell that is not valid JSON is a parse problem and is reported
here; one that is valid JSON but fails the field's constraints is a validation
problem and is not this module's business. That is what lets the importer
promise "the whole file is parsed before anything is written" — a parse that
could also reject on schema grounds would have to be re-run after every write.

Two shapes go in. JSON is the export's own document or a bare list of rows. CSV
is the export's header-driven table, read by the ``csv`` module rather than by
splitting on commas: a quoted value containing a comma, a quote or a newline is
ordinary content, and a hand-rolled split turns each into extra columns. Each
CSV cell is un-escaped on the way through (:func:`_unescape`), the exact
inverse of what the exporter applies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from sm_records._text import NUL_PROBLEM, has_nul
from sm_records.constants import ORPHANED_KEY
from sm_records.contracts.io import ImportRowError
from sm_records.services._export_cells import ENVELOPE_COLUMNS
from sm_records.services.errors import ImportParseFailed, PayloadTooLarge

__all__ = ["ImportRow", "ParsedFile", "nul_error", "parse_json", "too_many_rows"]


def too_many_rows(limit: int) -> PayloadTooLarge:
    """``max_import_rows``, as a 413 — the status ``max_import_bytes`` uses.

    The same kind of refusal for the same kind of reason: this file is more
    work than one request will do. It names the ceiling rather than the
    count, because the CSV path stops reading at the first row past it and
    therefore does not know how many more there are.
    """
    return PayloadTooLarge(f"the file holds more than {limit} rows, over the {limit}-row limit")


def nul_error(number: int, name: str | None, uuid: Any = None) -> ImportRowError:
    """One row's refusal for a cell carrying ``\x00``.

    A *row* error and not a failure for the whole file: a NUL reaching the
    database is a driver-level 500, so under ``on_error=skip`` one bad cell in
    a 10,000-row file used to discard the other 9,999. Reported here rather
    than left to the payload validator because the envelope columns (``slug``,
    ``translation_group``, ``uuid``) never reach it and are columns all the same.
    """
    return ImportRowError(
        row=number, field=name, uuid=None if uuid is None else str(uuid), message=NUL_PROBLEM
    )


_ROW_KEYS = frozenset({*ENVELOPE_COLUMNS, "data", "version"})
"""Top-level keys a JSON row may carry. ``published_at`` is accepted and
ignored — it is in every export, and refusing a key the exporter writes would
make the round trip a lie — but it is *derived* on write (a record is stamped
when it is published, ``services.records._published_at``), so honouring it
would let a file backdate a publication that never happened."""


@dataclass(slots=True)
class ImportRow:
    """One row of the file, in the file's own terms.

    ``number`` counts data rows from 1 and skips the CSV header, because it is
    there to be found again in a spreadsheet. ``present`` records which
    envelope columns the file actually carried, which is not the same question
    as which of them are ``None``: a file with no ``slug`` column leaves the
    slug alone, and a file with an empty ``slug`` cell clears it.
    """

    number: int
    data: dict[str, Any] = dc_field(default_factory=dict)
    envelope: dict[str, Any] = dc_field(default_factory=dict)
    stored: dict[str, Any] | None = None
    values: dict[str, Any] | None = None
    locale: str | None = None
    """The row's content locale, **resolved** — filled by ``import_._validate``
    once the configured list is in reach, so everything downstream (the slug
    match, the write) reads a real content locale rather than whatever the file
    spelled. ``None`` until then."""

    @property
    def uuid(self) -> str | None:
        value = self.envelope.get("uuid")
        return str(value) if value else None

    @property
    def version(self) -> int | None:
        value = self.envelope.get("version")
        return None if value in (None, "") else int(value)


@dataclass(slots=True)
class ParsedFile:
    rows: list[ImportRow]
    errors: list[ImportRowError]


def parse_json(text: str, *, max_rows: int) -> ParsedFile:
    """The export document, or a bare list of rows.

    ``max_rows`` is checked on the parsed document, before a single row is
    turned into an ``ImportRow`` — ``json.loads`` has already bounded the
    work by ``max_import_bytes``, and ``len()`` of the result is the exact
    count, so this is the cheap and exact half of the ceiling.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImportParseFailed(
            f"the file is not valid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}"
        ) from exc
    if isinstance(document, dict):
        records = document.get("records")
        if not isinstance(records, list):
            raise ImportParseFailed(
                "a JSON import must be a list of records, or an object with a 'records' list"
            )
    elif isinstance(document, list):
        records = document
    else:
        raise ImportParseFailed("a JSON import must be a list of records or an export document")

    if len(records) > max_rows:
        raise too_many_rows(max_rows)

    rows: list[ImportRow] = []
    errors: list[ImportRowError] = []
    for number, raw in enumerate(records, start=1):
        if not isinstance(raw, dict):
            errors.append(ImportRowError(row=number, message="each record must be an object"))
            continue
        unknown = sorted(set(raw) - _ROW_KEYS)
        if unknown:
            errors.append(
                ImportRowError(row=number, message=f"unknown key(s) {unknown} on the record")
            )
            continue
        data = raw.get("data")
        if not isinstance(data, dict):
            errors.append(ImportRowError(row=number, message="'data' must be an object"))
            continue
        envelope = {key: raw[key] for key in _ROW_KEYS - {"data"} if key in raw}
        bad = next((key for key, value in envelope.items() if has_nul(value)), None)
        if bad is not None:
            errors.append(nul_error(number, bad))
            continue
        rows.append(ImportRow(number=number, data=dict(data), envelope=envelope))
    return ParsedFile(rows, errors)


def refuses_orphaned(row: ImportRow) -> ImportRowError | None:
    """``_orphaned`` is the module's own undo buffer for deleted fields (§8.2)
    and is refused on every write path; an import is not an exception. A file
    that carried it would either invent recovery data nobody wrote or — far
    likelier, since an export never emits it — silently erase it."""
    if ORPHANED_KEY not in row.data:
        return None
    return ImportRowError(
        row=row.number,
        uuid=row.uuid,
        field=ORPHANED_KEY,
        message=f"{ORPHANED_KEY!r} is reserved and cannot be imported",
    )
