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
    return f"%{like_escape(term)}%"


def prefix_range(term: str) -> tuple[str, str | None]:
    r"""``(low, high)`` such that ``low <= value < high`` is exactly "starts
    with ``term``" — the half-open range a btree can answer by seeking.

    ``LIKE 'term%'`` expresses the same set and **cannot be answered from an
    index on SQLite**: the LIKE optimisation needs a ``NOCASE``-collated index
    when ``case_sensitive_like`` is off (the default), and every index here is
    ``BINARY``. Postgres is the same story under any non-C collation. A range
    is the portable spelling of a prefix search, and it is what makes
    ``ix_records_record_type_title_id`` able to serve the relation picker.

    The upper bound is the term with its last code point incremented, which is
    the *tight* bound: a value strictly between ``term`` and that successor
    must have ``term`` as a prefix, and every value that does is below it.
    Surrogates are stepped over because a lone one is not encodable, and a
    term made entirely of the maximum code point has no successor at all —
    ``high`` is ``None`` there and the caller drops the upper bound, which
    over-matches by nothing a real title contains.

    The cost is that this is **case- and collation-sensitive**, where
    ``contains`` is neither. That is the operator's contract, stated in the
    README: ``starts_with`` is the cheap, exact one and ``contains`` is the
    forgiving, expensive one, and the picker asks in that order.
    """
    for position in range(len(term) - 1, -1, -1):
        point = ord(term[position]) + 1
        if point == 0xD800:
            point = 0xE000
        if point <= 0x10FFFF:
            return term, term[:position] + chr(point)
    return term, None


def like_escape(term: str) -> str:
    """The literal-match escaping both patterns above share."""
    return term.translate(str.maketrans({"%": r"\%", "_": r"\_", "\\": "\\\\"}))


class FilterOp(str, enum.Enum):  # noqa: UP042
    EQ = "eq"
    NE = "ne"
    IN = "in"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
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


SORT_ATTR: dict[IndexKind, str] = {
    IndexKind.TEXT: "value",
    IndexKind.NUMBER: "value",
    IndexKind.BOOL: "value",
    IndexKind.DATE: "value",
    IndexKind.DATETIME: "value",
    IndexKind.REF: "target_uuid",
}
"""Which *attribute name* carries the sortable value, per kind.

The name and not the bound column, for two reasons that became one. A sort
joins an ``aliased()`` copy of the table (:mod:`sm_records.index._sorting`) and
the column on the alias is a different object from the one on the class; and
since Phase 5 §6 the class itself depends on which **table set** the type lives
in, so there is no one bound column left to name. Every builder below resolves
it with :func:`sort_column` against the table it was handed."""


def sort_column(table: Any, kind: IndexKind) -> Any:
    """The sortable/comparable column of one index table, per kind."""
    return getattr(table, SORT_ATTR[kind])


_ORDERED = frozenset({FilterOp.GT, FilterOp.GTE, FilterOp.LT, FilterOp.LTE})
_ALLOWED: dict[IndexKind, frozenset[FilterOp]] = {
    # Text is not ordered-comparable on purpose: ``value`` holds only the
    # first 512 characters, so ``>`` over it would answer with a prefix.
    IndexKind.TEXT: frozenset(
        {FilterOp.EQ, FilterOp.NE, FilterOp.IN, FilterOp.CONTAINS, FilterOp.STARTS_WITH}
    ),
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


def _text_eq(table: Any, value: str) -> ColumnElement[bool]:
    """Design doc §7.4. ``value_full IS NULL`` *is* the assertion that the
    indexed column holds the whole string, so a short needle must demand it —
    otherwise a 600-character value whose first 512 match is a false positive.
    """
    head = value[:TEXT_INDEX_LEN]
    if len(value) <= TEXT_INDEX_LEN:
        return and_(table.value == head, table.value_full.is_(None))
    return and_(table.value == head, table.value_full == value)


def starts_with_clause(column: Any, value: str) -> ColumnElement[bool]:
    """``value <= column < successor`` — see :func:`prefix_range`."""
    low, high = prefix_range(value)
    return and_(column >= low, column < high) if high is not None else column >= low


def _text_starts_with(table: Any, value: str) -> ColumnElement[bool]:
    """Design doc §7.4 again, and the easy half of it.

    ``value`` holds the first :data:`~sm_records.constants.TEXT_INDEX_LEN`
    characters, so for a needle no longer than that the prefix is *entirely*
    inside the indexed column and no ``value_full`` re-check is possible or
    needed — unlike ``eq``, a prefix match cannot be a false positive because
    of what was cut off. A longer needle is the reverse: ``value`` can only
    confirm its first 512 characters, so the rest is checked against
    ``value_full``, which by construction is non-NULL whenever the stored
    value was long enough to match at all.
    """
    if len(value) <= TEXT_INDEX_LEN:
        return starts_with_clause(table.value, value)
    return and_(
        table.value == value[:TEXT_INDEX_LEN],
        starts_with_clause(table.value_full, value),
    )


def _text_clause(table: Any, op: FilterOp, value: Any, field: str) -> ColumnElement[bool]:
    if op is FilterOp.CONTAINS:
        pattern = like_contains_pattern(_coerce(IndexKind.TEXT, value, field))
        # ``value_full`` too, or a match straddling the cut is invisible.
        return or_(
            table.value.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
            table.value_full.ilike(pattern, escape=LIKE_ESCAPE_CHAR),
        )
    if op is FilterOp.STARTS_WITH:
        return _text_starts_with(table, _coerce(IndexKind.TEXT, value, field))
    return _text_eq(table, _coerce(IndexKind.TEXT, value, field))


def _scalar_clause(
    table: Any, kind: IndexKind, op: FilterOp, value: Any, field: str
) -> ColumnElement[bool]:
    column = sort_column(table, kind)
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


def value_clause(
    table: Any, kind: IndexKind, op: FilterOp, value: Any, field: str
) -> ColumnElement[bool]:
    """The predicate over one index row, for every op but ``is_null``.

    ``ne`` returns the *positive* clause: the caller negates the whole EXISTS,
    which is the only correct reading for a multi-valued field — "no value
    equals x", not "some value differs from x".

    ``table`` is the index class of the caller's table set (Phase 5 §6.3) — the
    global ``records_index_text`` or a collection's copy of it. A parameter
    rather than a lookup here, because this module knows nothing about types
    and a kind on its own no longer names a table.
    """
    if op not in _ALLOWED[kind]:
        raise QueryError(
            field, "unsupported_op", f"{field!r}: {op.value} is not valid on {kind.value}"
        )
    if op is FilterOp.IN:
        values = (
            value if isinstance(value, Sequence) and not isinstance(value, str | bytes) else [value]
        )
        clauses = [value_clause(table, kind, FilterOp.EQ, item, field) for item in values]
        return or_(*clauses) if clauses else _never()
    if kind is IndexKind.TEXT:
        return _text_clause(table, op, value, field)
    return _scalar_clause(table, kind, op, value, field)


def _never() -> ColumnElement[bool]:
    """An empty ``in`` matches nothing — and says so in SQL rather than by
    being dropped, which would silently widen the query to every record."""
    return false()
