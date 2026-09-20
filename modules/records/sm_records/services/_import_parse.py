"""Turning an uploaded file into rows, before anything is validated or written.

The division of labour with :mod:`sm_records.services.import_` is strict and
worth keeping: **this module decides what the file says, and never what it
means.** A cell that is not valid JSON is a parse problem and is reported
here; a cell that is valid JSON but fails the field's constraints is a
validation problem and is not this module's business. That is what lets the
importer promise "the whole file is parsed before anything is written" — a
parse that could also reject on schema grounds would have to be re-run after
every write to stay true.

Two shapes go in. JSON is the export's own document (``{"type": …,
"records": […]}``) or a bare list of rows, because one of those is what you
get by exporting and the other is what you get by writing the file by hand.
CSV is the export's header-driven table, read by the ``csv`` module rather
than by splitting on commas: a quoted value containing a comma, a quote or a
newline is ordinary content, and a hand-rolled split silently turns each of
them into extra columns.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from sm_records.constants import ORPHANED_KEY
from sm_records.contracts.io import ImportRowError
from sm_records.schema.fields import FieldDefinition
from sm_records.schema.types import FieldType
from sm_records.services.errors import ImportParseFailed
from sm_records.services.export import ENVELOPE_COLUMNS

__all__ = ["ImportRow", "ParsedFile", "parse_csv", "parse_json"]

_JSON_CELL_TYPES = frozenset({FieldType.MULTISELECT, FieldType.JSON, FieldType.MEDIA})

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


def parse_json(text: str) -> ParsedFile:
    """The export document, or a bare list of rows."""
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
        rows.append(ImportRow(number=number, data=dict(data), envelope=envelope))
    return ParsedFile(rows, errors)


def _header(reader: Any, defs: list[FieldDefinition]) -> list[str]:
    try:
        raw_header = next(reader)
    except StopIteration:
        return []
    if raw_header and raw_header[0].startswith("﻿"):
        # Written by Excel, never by this module — see ``export.iter_csv``.
        raw_header[0] = raw_header[0][1:]
    header = [name.strip() for name in raw_header]
    known = {*ENVELOPE_COLUMNS, "version", *(field.key for field in defs)}
    unknown = sorted(set(header) - known)
    if unknown:
        raise ImportParseFailed(
            f"the header names column(s) {unknown} that this type has no field for"
        )
    return header


def parse_csv(text: str, defs: list[FieldDefinition]) -> ParsedFile:
    """Header-driven, so column order does not matter and a missing column
    means "leave it alone" rather than "clear it"."""
    by_key = {field.key: field for field in defs}
    # ``newline=""`` so a ``\r\n`` *inside* a quoted cell survives: StringIO's
    # default universal-newline translation would rewrite it to ``\n`` before
    # the csv reader ever sees the quotes, silently editing content.
    reader = csv.reader(io.StringIO(text, newline=""))
    header = _header(reader, defs)
    if not header:
        return ParsedFile([], [])

    rows: list[ImportRow] = []
    errors: list[ImportRowError] = []
    for number, raw_row in enumerate(reader, start=1):
        if not any(cell.strip() for cell in raw_row):
            continue
        if len(raw_row) != len(header):
            errors.append(
                ImportRowError(
                    row=number,
                    message=f"has {len(raw_row)} cell(s), but the header declares {len(header)}",
                )
            )
            continue
        data: dict[str, Any] = {}
        envelope: dict[str, Any] = {}
        failed = False
        for name, cell in zip(header, raw_row, strict=True):
            field = by_key.get(name)
            if field is None:
                envelope[name] = cell
                continue
            try:
                data[name] = _decode_cell(field, cell)
            except ValueError as exc:
                errors.append(
                    ImportRowError(
                        row=number, field=name, message=str(exc), uuid=envelope.get("uuid")
                    )
                )
                failed = True
        if not failed:
            rows.append(ImportRow(number=number, data=data, envelope=_clean(envelope)))
    return ParsedFile(rows, errors)


def _clean(envelope: dict[str, Any]) -> dict[str, Any]:
    """An empty cell is ``None``, not ``""``.

    ``position`` and ``version`` are the two that would otherwise reach the
    service as an empty string and blow up as a type error rather than as the
    "this column was left blank" the operator meant.
    """
    out: dict[str, Any] = {}
    for key, value in envelope.items():
        text = value.strip() if isinstance(value, str) else value
        out[key] = None if text == "" else text
    return out


def _decode_cell(field: FieldDefinition, cell: str) -> Any:
    """A CSV cell as the value the payload model will be handed.

    Deliberately *not* coercion: a scalar is passed through as its string and
    left for pydantic, so a ``number`` cell and a JSON ``number`` value go
    through exactly one coercion path rather than two that can disagree. Only
    the shapes CSV cannot spell flatly — a list, an object, a reference — are
    decoded here, inverting ``export.csv_cell``.
    """
    if cell == "":
        return None
    if field.type is FieldType.RELATION:
        return _decode_relation(field, cell)
    if field.type in _JSON_CELL_TYPES:
        try:
            return json.loads(cell)
        except json.JSONDecodeError as exc:
            raise ValueError(f"is not valid JSON: {exc.msg}") from exc
    return cell


def _decode_relation(field: FieldDefinition, cell: str) -> Any:
    if cell.startswith("["):
        try:
            items = json.loads(cell)
        except json.JSONDecodeError as exc:
            raise ValueError(f"is not a valid list of references: {exc.msg}") from exc
        if not isinstance(items, list):
            raise ValueError("must be a JSON list of 'type:uuid' references")
        return [_one_ref(item) for item in items]
    ref = _one_ref(cell)
    return [ref] if field.options.get("many") else ref


def _one_ref(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {"type": str(raw.get("type") or ""), "uuid": str(raw.get("uuid") or "")}
    text = str(raw)
    if ":" not in text:
        raise ValueError(f"reference {text!r} must be written as 'type:uuid'")
    type_key, uuid = text.split(":", 1)
    return {"type": type_key, "uuid": uuid}


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
