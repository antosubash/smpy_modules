"""The closed set of field types, and which index table each lands in.

A closed set rather than JSON Schema: it is renderable by a generic form,
diffable for schema evolution, and validatable with no new dependency.
Design doc §6.1. This file is the contract shared by the schema compiler
(``compile.py``), the index writer (``index/writer.py``) and the field
definition validator (``fields.py``) — change it here or nowhere.
"""

from __future__ import annotations

import enum
from typing import Final


class FieldType(str, enum.Enum):  # noqa: UP042
    TEXT = "text"
    LONGTEXT = "longtext"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    SELECT = "select"
    MULTISELECT = "multiselect"
    EMAIL = "email"
    URL = "url"
    JSON = "json"
    MEDIA = "media"
    RELATION = "relation"


class IndexKind(str, enum.Enum):  # noqa: UP042
    """Which ``records_index_*`` table a field's values are projected into."""

    TEXT = "text"
    NUMBER = "number"
    BOOL = "bool"
    DATE = "date"
    DATETIME = "datetime"
    REF = "ref"


INDEX_KIND: Final[dict[FieldType, IndexKind]] = {
    FieldType.TEXT: IndexKind.TEXT,
    FieldType.SELECT: IndexKind.TEXT,
    FieldType.MULTISELECT: IndexKind.TEXT,
    FieldType.EMAIL: IndexKind.TEXT,
    FieldType.URL: IndexKind.TEXT,
    FieldType.NUMBER: IndexKind.NUMBER,
    FieldType.INTEGER: IndexKind.NUMBER,
    FieldType.BOOLEAN: IndexKind.BOOL,
    FieldType.DATE: IndexKind.DATE,
    FieldType.DATETIME: IndexKind.DATETIME,
    FieldType.RELATION: IndexKind.REF,
}
"""Field types absent here — ``longtext``, ``json``, ``media`` — are not
indexable, and the schema validator refuses ``indexed: true`` on them."""

MULTI_VALUED: Final[frozenset[FieldType]] = frozenset({FieldType.MULTISELECT})
"""Types whose one value projects to several index rows (YesSql's 1:N map
index). A ``relation`` with ``options.many`` is multi-valued too, decided per
field rather than per type."""

NOT_UNIQUE: Final[frozenset[FieldType]] = frozenset(
    {FieldType.MULTISELECT, FieldType.LONGTEXT, FieldType.JSON, FieldType.MEDIA}
)
"""Types on which ``unique: true`` is meaningless and refused. A ``many``
relation joins this set per field."""


def indexable(field_type: FieldType) -> bool:
    return field_type in INDEX_KIND


class ChangeClass(str, enum.Enum):  # noqa: UP042
    """How a schema change is classified before anything is written.
    Design doc §8.2. Ordered by severity: the class of a whole diff is the
    highest class of any change in it."""

    ADDITIVE = "additive"
    """A new optional field, a new select choice, a relaxed constraint, a
    label/help edit. Applied immediately; existing records untouched."""
    INDEX_AFFECTING = "index_affecting"
    """Toggling ``indexed``, or a type change on an indexed field. Applied,
    then the field's index rows are rebuilt (§8.5) — the field is refused as
    a filter until that finishes."""
    RESTRICTIVE = "restrictive"
    """A new required field, a narrowed type, a tightened constraint, a
    removed choice, a newly unique field. Applied only after a dry run over
    existing records; refused unless every row passes, a default makes it
    pass, or ``force`` marks the failures instead."""
    DESTRUCTIVE = "destructive"
    """Deleting a field. The key leaves ``fields``; its values move to
    ``_orphaned`` lazily, on each record's next write (§8.3)."""


CHANGE_SEVERITY: Final[dict[ChangeClass, int]] = {
    ChangeClass.ADDITIVE: 0,
    ChangeClass.INDEX_AFFECTING: 1,
    ChangeClass.RESTRICTIVE: 2,
    ChangeClass.DESTRUCTIVE: 3,
}
