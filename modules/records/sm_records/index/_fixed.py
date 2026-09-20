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
    starts_with_clause,
)
from sm_records.models import Record, RecordStatus

__all__ = [
    "FIXED_COLUMNS",
    "NOT_NULL_FIXED_COLUMNS",
    "PUBLIC_FIXED_COLUMNS",
    "SORT_INDEXED_FIXED_COLUMNS",
    "fixed_clause",
]

FIXED_COLUMNS: frozenset[str] = frozenset(
    {
        "status",
        "display_title",
        "slug",
        "locale",
        "position",
        "published_at",
        "created_at",
        "updated_at",
    }
)
"""The projection every record has regardless of its type — the module's
``ContentItemIndex``. Filterable and sortable directly, with no index table
and no ``indexed: true`` anywhere.

``locale`` is here rather than in an index table because a record's language is
a property of the *document*, like its status: the ``records_index_*`` tables
are untouched by content i18n, and ``filter=locale:eq:de`` is an ordinary
column predicate (Phase 5 §4.1). Membership here is also what reserves the key
— ``constants.RESERVED_FIELD_KEYS`` derives from this set plus the ``Record``
columns — so no type can declare a field called ``locale`` and have it answered
from the wrong place."""

PUBLIC_FIXED_COLUMNS: frozenset[str] = FIXED_COLUMNS & frozenset(
    {"slug", "display_title", "published_at"}
)
"""The fixed columns the **anonymous** read API may be asked about (§10).

Exactly the ones its response shape carries
(:class:`~sm_records.contracts.public.PublicRecordRead`), and derived from
:data:`FIXED_COLUMNS` so a column renamed out of the record row cannot
survive here. The rest of the projection — ``status``, ``position``,
``created_at``, ``updated_at`` — is removed from the public *shape* on
purpose, and a grammar that still answered about it would let an anonymous
caller binary-search an audit timestamp to arbitrary precision and read the
internal ``position`` ordering of content it is only supposed to be able to
list. They are refused by name, the same 400 an unindexed field gets, rather
than answered.
"""

NOT_NULL_FIXED_COLUMNS: frozenset[str] = frozenset(
    name for name in FIXED_COLUMNS if not getattr(Record, name).property.columns[0].nullable
)
"""The fixed columns the database guarantees a value for.

Read off the mapped columns rather than listed by hand, because the list is
only ever used to *drop* a ``NULLS LAST`` wrapper (``index._sorting``) and
getting it wrong in that direction reorders a page. ``status``, ``position``,
``display_title`` and ``created_at`` are non-nullable today; ``slug``,
``published_at`` and ``updated_at`` are not, and keep the wrapper.

Dropping it matters because ``ORDER BY col NULLS LAST`` is not the order any
btree on ``col`` stores, so SQLite answers it with a temp B-tree over the
whole type even when the composite index of ``Record.__table_args__`` covers
the column exactly — 25 rows paid for with a sort of 9,000.
"""

SORT_INDEXED_FIXED_COLUMNS: frozenset[str] = frozenset(
    index.columns.keys()[1]
    for index in Record.__table__.indexes
    if len(index.columns) == 3 and index.columns.keys()[0::2] == ["type_id", "id"]
)
"""The fixed columns a ``(type_id, <column>, id)`` index can order directly.

Read off the model rather than listed, so adding such an index is the only
thing needed to make a sort on that column index-served — and dropping one
cannot leave this claiming otherwise. It is used for exactly one decision, in
:func:`sm_records.index._sorting.tiebreak_desc`: whether a *descending* sort
can be answered by reading that index backwards, end to end, with no sorter
at all. Everything else pays a sorter regardless, and there the tiebreaker
must stay ascending — see that function for what it costs when it does not.
"""

_FIXED_TEXT = frozenset({"display_title", "slug"})
"""Fixed columns ``contains``/``starts_with`` are meaningful on. ``locale`` is
deliberately not one: a language tag is matched whole (``eq``, ``ne``, ``in``),
and a prefix match over it would make ``de`` select ``de-AT`` on one install
and nothing on the next."""
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


def fixed_clause(record: Any, field: str, op: FilterOp, value: Any) -> ColumnElement[bool]:
    """Fixed columns are real columns, so these are ordinary predicates —
    except for ``ne``, which also matches a NULL. SQL's ``<> NULL`` is unknown
    and would drop rows with no slug from a "slug is not 'x'" filter, which is
    not what anybody means by it and disagrees with how ``ne`` reads on an
    index table (absence matches).

    ``record`` is the document class of the caller's table set (Phase 5 §6.3).
    The three derived sets above stay read off the **global** class on purpose:
    every set is built by one factory, so which columns exist, which are
    ``NOT NULL`` and which carry a ``(type_id, col, id)`` index are facts about
    the *shape*, and a collection cannot differ in any of them."""
    column = getattr(record, field)
    if op is FilterOp.IS_NULL:
        return column.is_(None) if value in (None, True) else column.isnot(None)
    if op is FilterOp.CONTAINS:
        if field not in _FIXED_TEXT:
            raise QueryError(field, "unsupported_op", "contains needs a text column")
        pattern = like_contains_pattern(_fixed_value(field, value))
        return column.ilike(pattern, escape=LIKE_ESCAPE_CHAR)
    if op is FilterOp.STARTS_WITH:
        if field not in _FIXED_TEXT:
            raise QueryError(field, "unsupported_op", "starts_with needs a text column")
        # A half-open range and not ``LIKE 'term%'`` — see
        # ``_predicates.prefix_range`` for why the range is the only spelling
        # an index can answer, and what it costs in case sensitivity.
        return starts_with_clause(column, _fixed_value(field, value))
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
