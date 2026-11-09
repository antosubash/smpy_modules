"""The column mapping of an import: the suggestion and the validation of a submitted one (R9).

Pure: no database. A mapping is ``{"fields": {"<column index>": "<field key>"}, "tags": bool}``.
A refusal names the column index or ``tags``, never a value (R16).
"""

from __future__ import annotations

from typing import Any

from sm_records.contracts.newsletter_import import ImportTargets

from sm_newsletter.core.errors_import import ImportBadMapping
from sm_newsletter.imports.constants import NAME_DEFAULTS

Mapping = dict[str, Any]

__all__ = ["Mapping", "suggest", "validate"]


def suggest(columns: list[dict], targets: ImportTargets, tags_found: list[dict]) -> Mapping:
    """First Name / Vorname and Last Name / Nachname onto the list's fields, when it has
    them; tags on when some were found and the list can hold them."""
    keys = {f.key for f in targets.fields}
    fields: dict[str, str] = {}
    for field, aliases in NAME_DEFAULTS.items():
        if field not in keys:
            continue
        for index, column in enumerate(columns):
            if column["key"] in aliases:
                fields[str(index)] = field
                break
    return {"fields": fields, "tags": bool(tags_found) and targets.tags != "missing"}


def validate(
    raw: object, *, columns: list[dict], targets: ImportTargets, tags_found: list[dict]
) -> Mapping:
    """The submitted mapping, normalised; :class:`ImportBadMapping` for an unknown column,
    an unknown or non-mappable field, one field twice, or tags on a list that cannot hold them."""
    if not isinstance(raw, dict):
        raise ImportBadMapping("The column mapping is not valid (mapping)")
    chosen = raw.get("fields", {})
    if not isinstance(chosen, dict):
        raise ImportBadMapping("The column mapping is not valid (fields)")
    allowed = {f.key for f in targets.fields}
    fields: dict[str, str] = {}
    used: set[str] = set()
    for column, key in chosen.items():
        where = f"fields.{str(column)[:20]}"
        if not _is_column(column, len(columns)) or not isinstance(key, str) or key not in allowed:
            raise ImportBadMapping(f"The column mapping is not valid ({where})")
        if key in used:
            raise ImportBadMapping(f"The column mapping is not valid ({where})")
        canonical = str(int(column))  # "007" is column 7: the staged rows are keyed "7"
        if canonical in fields:
            raise ImportBadMapping(f"The column mapping is not valid ({where})")
        used.add(key)
        fields[canonical] = key
    tags = raw.get("tags", False)
    if not isinstance(tags, bool) or (tags and targets.tags == "missing"):
        raise ImportBadMapping("The column mapping is not valid (tags)")
    return {"fields": fields, "tags": tags}


def _is_column(column: object, count: int) -> bool:
    # The length bound keeps ``int()`` under Python's 4300-digit limit (a ValueError, a 500).
    return (
        isinstance(column, str)
        and len(column) <= 9
        and column.isascii()
        and column.isdigit()
        and int(column) < count
    )
