"""Reading the parts of a field definition the index layer needs.

``RecordType.fields`` is plain JSON — a list of dicts, validated elsewhere
(``sm_records.schema``). This module deliberately consumes that raw shape
rather than importing the schema package: the index layer runs against
*stored* definitions, including ones written by an older schema version, and a
stricter reader would raise on a row it is supposed to be able to reindex.

Only four properties matter here — the key, the type, whether it is indexed
and whether one value projects to several rows. Everything else (labels,
constraints, defaults) belongs to validation and rendering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sm_records.schema.types import INDEX_KIND, MULTI_VALUED, FieldType, IndexKind


@dataclass(frozen=True, slots=True)
class IndexedField:
    """A field definition reduced to what the writer and the query builder use."""

    key: str
    type: FieldType
    kind: IndexKind
    many: bool
    """One value, several index rows — a ``multiselect``, or a to-many
    ``relation``. Decided per field, not per type, which is why it is read from
    ``options.many`` as well as from the type table."""


def read_field(raw: dict[str, Any]) -> IndexedField | None:
    """Reduce one raw definition, or ``None`` if it is not a queryable field.

    Returns ``None`` for an unindexed field, an unindexable type, and a type
    this build does not know — a definition written by a newer version of the
    module must not stop the reindex of its siblings.
    """
    if not raw.get("indexed"):
        return None
    try:
        field_type = FieldType(raw.get("type"))
    except ValueError:
        return None
    kind = INDEX_KIND.get(field_type)
    if kind is None:
        return None
    options = raw.get("options") or {}
    many = field_type in MULTI_VALUED or bool(options.get("many"))
    return IndexedField(key=str(raw.get("key")), type=field_type, kind=kind, many=many)


def indexed_fields(fields: list[dict[str, Any]]) -> list[IndexedField]:
    """Every field of a type that has index rows, in declaration order."""
    return [f for f in (read_field(raw) for raw in fields) if f is not None]


def indexed_map(fields: list[dict[str, Any]]) -> dict[str, IndexedField]:
    return {f.key: f for f in indexed_fields(fields)}


def declared_keys(fields: list[dict[str, Any]]) -> set[str]:
    """Every key the type declares, indexed or not — the query builder needs
    the difference between "no such field" and "that field is not queryable"."""
    return {str(raw["key"]) for raw in fields if raw.get("key")}


def relation_target(raw: dict[str, Any]) -> str | None:
    """The type key a ``relation`` field points at."""
    return (raw.get("options") or {}).get("target_type")
