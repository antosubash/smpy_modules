"""One row of an export file, cell by cell — and what is safe to open.

Split from :mod:`sm_records.services.export` for the 300-line cap, along the
seam that module already had between *walking* the type (keyset-paged,
constant-memory, shared by both formats) and *spelling* a value. Everything
here is pure: a value in, a string out, no session and no settings.

The one rule here that is not merely formatting is :func:`escape_formula`.

Re-exported from ``export``, so no caller has to learn this module exists.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sm_records.schema.compile import to_jsonable
from sm_records.schema.fields import FieldDefinition
from sm_records.schema.types import FieldType

__all__ = [
    "APOSTROPHE",
    "ENVELOPE_COLUMNS",
    "FORMULA_LEADERS",
    "csv_cell",
    "csv_header",
    "escape_formula",
]

APOSTROPHE = "'"
"""The escape character, named because it is easy to mistake for a quote in a
source file full of them."""


ENVELOPE_COLUMNS = (
    "uuid",
    "slug",
    "locale",
    "translation_group",
    "status",
    "position",
    "published_at",
)
"""The fixed columns of §5 that travel with every record, whatever its type.

``locale`` and ``translation_group`` travel because a file that lost them
could not be imported back into a multilingual install without silently
collapsing every record into the default language and breaking every
translation group apart (Phase 5 §4.3). ``translation_group`` is opaque to the
importer — it is carried, never interpreted.

First rather than last in the CSV: ``uuid`` is the column an operator edits a
file *against* (it is what ``match_by`` defaults to), and a spreadsheet whose
identity column is off the right-hand edge past forty user fields is one
people mis-align by hand. The declared fields follow, in declaration order.
Import is driven by the header row, so neither order is load-bearing on the
way back in.
"""


_JSON_CELL_TYPES = frozenset({FieldType.MULTISELECT, FieldType.JSON, FieldType.MEDIA})
"""Field types whose value is JSON-encoded inside its CSV cell. A list or an
object has no flat spelling that survives a round trip, and inventing one
(semicolons, repeated columns) is how a value containing the separator
silently becomes two values."""


def csv_cell(field: FieldDefinition | None, value: Any) -> str:
    """One payload value as its CSV cell.

    The wire form the module already uses, never a new one: a ``number`` is
    the decimal *string* ``to_jsonable`` stores (a float round trip is the
    precision loss §7.3 exists to prevent), a boolean is ``true``/``false``
    rather than Python's capitalised spelling, and a date is ISO because that
    is what the payload holds.

    A relation is ``type:uuid`` — flat, greppable, and unambiguous because
    neither half can contain a colon (``TYPE_KEY_PATTERN``, and a uuid is
    hex). A to-many relation is a JSON list of those, for the same reason
    ``multiselect`` is a JSON list: any flat separator is a value somebody's
    content contains.

    **Then :func:`escape_formula`, on every cell without exception** — the
    envelope columns included, because ``translation_group`` is carried
    through an import verbatim and is therefore as caller-chosen as any
    payload value. Uniformity is also what makes the strip on the way back in
    a single rule rather than a per-column table.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if field is not None and field.type is FieldType.RELATION:
        return escape_formula(_relation_cell(value))
    if field is not None and field.type in _JSON_CELL_TYPES:
        return escape_formula(json.dumps(to_jsonable(value)))
    if isinstance(value, Decimal | datetime | date):
        return escape_formula(str(to_jsonable(value)))
    if isinstance(value, list | dict):
        return escape_formula(json.dumps(to_jsonable(value)))
    return escape_formula(str(value))


FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r", APOSTROPHE)
"""First characters a spreadsheet reads as the start of a formula — plus the
apostrophe itself, which is what makes the escape reversible.

``=cmd|' /C calc'!A0`` stored in a ``text`` field was exported verbatim into a
file served as ``Content-Disposition: attachment``, i.e. straight into the
spreadsheet of whichever admin clicked Export, and any caller who can create a
record chooses that value. The conventional mitigation is a leading
apostrophe, which Excel and LibreOffice both read as "the rest of this cell is
literal text".

Escaping the apostrophe **too** is what keeps the file round-tripping, and is
the whole answer to the objection this module used to record here — that the
prefix is lossy because an importer cannot tell it from a value that genuinely
starts with one. It can, if the exporter doubles it: exactly one apostrophe is
added on the way out and exactly one taken off on the way in
(:func:`sm_records.services._import_parse.parse_csv`), for every cell, and the
pair is lossless. The cost is a *hand-written* CSV, which has no doubling and
loses a leading apostrophe on import; the README says so.
"""


def escape_formula(cell: str) -> str:
    """One cell, safe to open in a spreadsheet. See :data:`FORMULA_LEADERS`."""
    return APOSTROPHE + cell if cell.startswith(FORMULA_LEADERS) else cell


def _relation_cell(value: Any) -> str:
    if isinstance(value, list):
        return json.dumps([_one_ref(item) for item in value])
    return _one_ref(value)


def _one_ref(value: Any) -> str:
    if isinstance(value, dict):
        return f"{value.get('type') or ''}:{value.get('uuid') or ''}"
    return str(value)


def csv_header(defs: list[FieldDefinition]) -> list[str]:
    return [*ENVELOPE_COLUMNS, *(field.key for field in defs)]
