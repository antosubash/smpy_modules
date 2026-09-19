"""The fixed-column half of the filter grammar — design §7.2's
``ContentItemIndex``.

Every record has this projection whatever its type declares: ``status``,
``display_title``, ``slug``, ``position``, ``published_at``, ``created_at``,
``updated_at``. They are real columns on ``records_record``, so a filter over
one is an ordinary predicate with no index table, no ``indexed: true`` and no
semi-join — which is exactly why they live here and not in
:mod:`sm_records.index.query`, whose whole subject is the other kind: which
index table, which record, which refusal.

Split out of ``query`` for the 300-line cap, along the seam that was already
there.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.sql import ColumnElement

from sm_records.index._coerce import coerce_datetime, coerce_text
from sm_records.index._predicates import (
    LIKE_ESCAPE_CHAR,
    FilterOp,
    QueryError,
    like_contains_pattern,
)
from sm_records.models import Record, RecordStatus

__all__ = ["FIXED_COLUMNS", "fixed_clause"]

FIXED_COLUMNS: frozenset[str] = frozenset(
    {"status", "display_title", "slug", "position", "published_at", "created_at", "updated_at"}
)
"""The projection every record has regardless of its type — the module's
``ContentItemIndex``. Filterable and sortable directly, with no index table
and no ``indexed: true`` anywhere."""

_FIXED_TEXT = frozenset({"display_title", "slug"})
_FIXED_ORDERED = frozenset({"position", "published_at", "created_at", "updated_at"})
_ORDER_OPS = frozenset({FilterOp.GT, FilterOp.GTE, FilterOp.LT, FilterOp.LTE})


def _fixed_value(field: str, value: Any) -> Any:
    if field == "status":
        try:
            return RecordStatus(value)
        except ValueError as exc:
            raise QueryError(field, "bad_value", f"unknown status {value!r}") from exc
    if field == "position":
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise QueryError(field, "bad_value", f"{field!r} takes an integer") from exc
    if field in _FIXED_ORDERED:
        moment: datetime | None = coerce_datetime(value)
        if moment is None:
            raise QueryError(field, "bad_value", f"{field!r} takes an aware datetime")
        return moment
    text = coerce_text(value)
    if text is None:
        raise QueryError(field, "bad_value", f"{field!r} takes a string")
    return text


def fixed_clause(field: str, op: FilterOp, value: Any) -> ColumnElement[bool]:
    """Fixed columns are real columns, so these are ordinary predicates —
    except for ``ne``, which also matches a NULL. SQL's ``<> NULL`` is unknown
    and would drop rows with no slug from a "slug is not 'x'" filter, which is
    not what anybody means by it and disagrees with how ``ne`` reads on an
    index table (absence matches)."""
    column = getattr(Record, field)
    if op is FilterOp.IS_NULL:
        return column.is_(None) if value in (None, True) else column.isnot(None)
    if op is FilterOp.CONTAINS:
        if field not in _FIXED_TEXT:
            raise QueryError(field, "unsupported_op", "contains needs a text column")
        pattern = like_contains_pattern(_fixed_value(field, value))
        return column.ilike(pattern, escape=LIKE_ESCAPE_CHAR)
    if op in _ORDER_OPS and field not in _FIXED_ORDERED:
        raise QueryError(field, "unsupported_op", f"{op.value} needs an ordered column")
    if op is FilterOp.IN:
        raw = value if isinstance(value, Sequence) and not isinstance(value, str) else []
        return column.in_([_fixed_value(field, item) for item in raw])
    coerced = _fixed_value(field, value)
    if op is FilterOp.EQ:
        return column == coerced
    if op is FilterOp.NE:
        return or_(column != coerced, column.is_(None))
    return {
        FilterOp.GT: column > coerced,
        FilterOp.GTE: column >= coerced,
        FilterOp.LT: column < coerced,
        FilterOp.LTE: column <= coerced,
    }[op]
