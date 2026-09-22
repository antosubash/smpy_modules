"""Reading the CSV half of an import — the header, the rows, the cells.

Split from :mod:`sm_records.services._import_parse` for the 300-line cap,
along the seam that module's docstring already draws: JSON arrives as a
document ``json.loads`` has already shaped, and everything below is about the
one format that has to be *read*. The row types, the row-level errors and the
JSON parse stay there; this is the table reader.

Two rules that are easy to lose here:

* every cell is un-escaped (:func:`_unescape`), the exact inverse of
  :func:`sm_records.services._export_cells.escape_formula`;
* ``max_rows`` is counted as the rows are read rather than checked up front,
  because a quoted cell may contain newlines and there is therefore no cheap
  exact count to check.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from sm_records._text import has_nul
from sm_records.contracts.io import ImportRowError
from sm_records.schema.fields import FieldDefinition
from sm_records.schema.types import FieldType
from sm_records.services._export_cells import APOSTROPHE, ENVELOPE_COLUMNS
from sm_records.services._import_parse import (
    ImportRow,
    ParsedFile,
    nul_error,
    too_many_rows,
)
from sm_records.services.errors import ImportParseFailed

__all__ = ["parse_csv"]


_JSON_CELL_TYPES = frozenset({FieldType.MULTISELECT, FieldType.JSON, FieldType.MEDIA})


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


def parse_csv(text: str, defs: list[FieldDefinition], *, max_rows: int) -> ParsedFile:
    """Header-driven, so column order does not matter and a missing column
    means "leave it alone" rather than "clear it".

    ``max_rows`` is counted as the rows are read and refused at the first one
    past the ceiling. There is no cheap exact count to check first — a quoted
    cell may contain newlines, so counting them over-counts and would refuse
    files that are inside the limit — and stopping at ``max_rows + 1`` bounds
    the work just as well.
    """
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
        if number > max_rows:
            raise too_many_rows(max_rows)
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
        for name, raw_cell in zip(header, raw_row, strict=True):
            field = by_key.get(name)
            cell = _unescape(raw_cell)
            if has_nul(cell):
                errors.append(nul_error(number, name, envelope.get("uuid")))
                failed = True
                continue
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


def _unescape(cell: str) -> str:
    """Undo :func:`sm_records.services._export_cells.escape_formula` — exactly
    one leading apostrophe, from every cell.

    Every cell, not only the ones that look dangerous: the escape doubles an
    apostrophe that was already there, so ``''x`` is the content ``'x`` and
    ``'x`` is the content ``x``. One added on the way out, one taken off on the
    way in, and the round trip is lossless. It stays lossless over the
    exporter's one exemption too — a plain negative number is written bare, so
    there is no apostrophe here to take off and ``-5`` reads back as ``-5``.
    The cost is a CSV written *by hand*, which carries no doubling and loses a
    leading apostrophe — the README states that next to the export.
    """
    return cell[1:] if cell.startswith(APOSTROPHE) else cell


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
