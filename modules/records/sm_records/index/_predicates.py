"""Per-kind value predicates — the half of the filter grammar that knows SQL.

Split out of ``query`` so each stays readable and under the file cap: this
module answers "what does ``price >= 10`` look like against
``records_index_number``", and ``query`` answers "which table, which record,
which error".

``FilterOp`` and ``QueryError`` live here because every builder below needs
both; ``query`` re-exports them, and that is the public surface.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, false, or_
from sqlalchemy.sql import ColumnElement

from sm_records.constants import TEXT_INDEX_LEN
from sm_records.index._coerce import (
    coerce_bool,
    coerce_date,
    coerce_datetime,
    coerce_number,
    coerce_ref,
    coerce_text,
)
from sm_records.models import (
    IndexBool,
    IndexDate,
    IndexDatetime,
    IndexNumber,
    IndexRef,
    IndexText,
)
from sm_records.schema.types import IndexKind

LIKE_ESCAPE_CHAR = "\\"


def like_contains_pattern(term: str) -> str:
    r"""A LIKE pattern matching ``term`` literally, wildcards and all.

    The framework grew ``simple_module_db.search`` for this, but a published
    module depends on the framework with a *range* (CLAUDE.md) and that helper
    is not in the oldest release in ours — importing it would make this module
    uninstallable on a host that is merely a little behind. ``news.like`` keeps
    its own copy for the same reason.

    Every caller must also pass ``escape=LIKE_ESCAPE_CHAR``: without the ESCAPE
    clause the backslashes below are ordinary characters, so the pattern
    demands a literal backslash no real content has and the search silently
    returns nothing — strictly worse than the over-matching it prevents.
    """
    escaped = term.translate(str.maketrans({"%": r"\%", "_": r"\_", "\\": "\\\\"}))
    return f"%{escaped}%"


class FilterOp(str, enum.Enum):  # noqa: UP042
    EQ = "eq"
    NE = "ne"
    IN = "in"
    CONTAINS = "contains"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IS_NULL = "is_null"


class QueryError(ValueError):
    """A filter or sort the index cannot answer.

    ``reason`` is what a caller maps to a status code: ``reindexing`` is the
    409 of design doc §8.5 — a *temporary* refusal while the field's rows move
    between tables — and everything else is a 400. Refusing loudly for a few
    seconds is the whole point; partial results returned without comment are
    the failure worth this ceremony.
    """

    def __init__(self, field: str, reason: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.reason = reason


INDEX_TABLE: dict[IndexKind, Any] = {
    IndexKind.TEXT: IndexText,
    IndexKind.NUMBER: IndexNumber,
    IndexKind.BOOL: IndexBool,
    IndexKind.DATE: IndexDate,
    IndexKind.DATETIME: IndexDatetime,
    IndexKind.REF: IndexRef,
}

SORT_COLUMN: dict[IndexKind, Any] = {
    IndexKind.TEXT: IndexText.value,
    IndexKind.NUMBER: IndexNumber.value,
    IndexKind.BOOL: IndexBool.value,
    IndexKind.DATE: IndexDate.value,
    IndexKind.DATETIME: IndexDatetime.value,
    IndexKind.REF: IndexRef.target_uuid,
}

_ORDERED = frozenset({FilterOp.GT, FilterOp.GTE, FilterOp.LT, FilterOp.LTE})
_ALLOWED: dict[IndexKind, frozenset[FilterOp]] = {
    # Text is not ordered-comparable on purpose: ``value`` holds only the
    # first 512 characters, so ``>`` over it would answer with a prefix.
    IndexKind.TEXT: frozenset({FilterOp.EQ, FilterOp.NE, FilterOp.IN, FilterOp.CONTAINS}),
    IndexKind.NUMBER: frozenset({FilterOp.EQ, FilterOp.NE, FilterOp.IN, *_ORDERED}),
    IndexKind.BOOL: frozenset({FilterOp.EQ, FilterOp.NE}),
    IndexKind.DATE: frozenset({FilterOp.EQ, FilterOp.NE, FilterOp.IN, *_ORDERED}),
    IndexKind.DATETIME: frozenset({FilterOp.EQ, FilterOp.NE, FilterOp.IN, *_ORDERED}),
    IndexKind.REF: frozenset({FilterOp.EQ, FilterOp.NE, FilterOp.IN}),
}

_COERCE = {
    IndexKind.TEXT: coerce_text,
    IndexKind.NUMBER: coerce_number,
    IndexKind.BOOL: coerce_bool,
    IndexKind.DATE: coerce_date,
    IndexKind.DATETIME: coerce_datetime,
}


def _coerce(kind: IndexKind, value: Any, field: str) -> Any:
    """Coerce a *filter* value exactly as the provider coerced the stored one.

    The same ``None`` that means "leave it out of the index" means "this
    filter cannot be expressed" here: the caller typed the value, so silence
    would be a query that quietly matches nothing.
    """
    if kind is IndexKind.REF:
        parsed = coerce_ref(value)
        out: Any = parsed[1] if isinstance(parsed, tuple) else parsed
    else:
        out = _COERCE[kind](value)
    if out is None:
        raise QueryError(field, "bad_value", f"{field!r}: {value!r} is not a valid value")
    return out


def _text_eq(value: str) -> ColumnElement[bool]:
    """Design doc §7.4. ``value_full IS NULL`` *is* the assertion that the
    indexed column holds the whole string, so a short needle must demand it —
    otherwise a 600-character value whose first 512 match is a false positive.
    """
    head = value[:TEXT_INDEX_LEN]
    if len(value) <= TEXT_INDEX_LEN:
        return and_(IndexText.value == head, IndexText.value_full.is_(None))
    return and_(IndexText.value == head, IndexText.value_full == value)


def _text_clause(op: FilterOp, value: Any, field: str) -> ColumnElement[bool]:
    if op is FilterOp.CONTAINS:
        pattern = like_contains_pattern(_coerce(IndexKind.TEXT, value, field))
        # ``value_full`` too, or a match straddling the cut is invisible.
        return or_(
            IndexText.value.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
            IndexText.value_full.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
        )
    return _text_eq(_coerce(IndexKind.TEXT, value, field))


def _scalar_clause(kind: IndexKind, op: FilterOp, value: Any, field: str) -> ColumnElement[bool]:
    column = SORT_COLUMN[kind]
    coerced = _coerce(kind, value, field)
    if op is FilterOp.GT:
        return column > coerced
    if op is FilterOp.GTE:
        return column >= coerced
    if op is FilterOp.LT:
        return column < coerced
    if op is FilterOp.LTE:
        return column <= coerced
    return column == coerced


def value_clause(kind: IndexKind, op: FilterOp, value: Any, field: str) -> ColumnElement[bool]:
    """The predicate over one index row, for every op but ``is_null``.

    ``ne`` returns the *positive* clause: the caller negates the whole EXISTS,
    which is the only correct reading for a multi-valued field — "no value
    equals x", not "some value differs from x".
    """
    if op not in _ALLOWED[kind]:
        raise QueryError(
            field, "unsupported_op", f"{field!r}: {op.value} is not valid on {kind.value}"
        )
    if op is FilterOp.IN:
        values = (
            value if isinstance(value, Sequence) and not isinstance(value, str | bytes) else [value]
        )
        clauses = [value_clause(kind, FilterOp.EQ, item, field) for item in values]
        return or_(*clauses) if clauses else _never()
    if kind is IndexKind.TEXT:
        return _text_clause(op, value, field)
    return _scalar_clause(kind, op, value, field)


def _never() -> ColumnElement[bool]:
    """An empty ``in`` matches nothing — and says so in SQL rather than by
    being dropped, which would silently widen the query to every record."""
    return false()
