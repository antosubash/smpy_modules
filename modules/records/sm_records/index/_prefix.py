"""``starts_with`` as a half-open range in code-point order — design doc §7.4.

Split from :mod:`sm_records.index._predicates` for the 300-line cap, along the
one seam that is dialect-aware: :class:`ByteOrdered` is the only place the
index layer renders differently per database.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.functions import FunctionElement

__all__ = ["ByteOrdered", "prefix_range", "starts_with_clause"]


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


class ByteOrdered(FunctionElement[str]):
    """``column`` compared in code-point order whatever the database collates by.

    :func:`prefix_range` is only a prefix test if ``<`` orders by code point.
    SQLite's default ``BINARY`` collation does; a Postgres database created
    with a linguistic locale (the ``postgres`` image's ``en_US.utf8``, any ICU
    locale) does not — there ``'item' <= 'ITEM' < 'iten'`` holds, so the range
    for ``item`` also answered ``ITEM``. On Postgres this renders
    ``(column COLLATE "C")``; every other dialect gets the bare column.

    The cost on Postgres is that the range can no longer use the
    ``(type_id, field_key, value)`` btree beyond its equality prefix: the rows
    of one field are read and filtered, not seeked. Correct first; an
    expression index on ``value COLLATE "C"`` is the remedy if a host measures
    the difference (see ``docs/postgres-2026-09-21.md``).
    """

    inherit_cache = True
    name = "byte_ordered"


@compiles(ByteOrdered)
def _byte_ordered_default(element: ByteOrdered, compiler: Any, **kw: Any) -> str:
    return compiler.process(element.clauses.clauses[0], **kw)


@compiles(ByteOrdered, "postgresql")
def _byte_ordered_postgresql(element: ByteOrdered, compiler: Any, **kw: Any) -> str:
    return f'({compiler.process(element.clauses.clauses[0], **kw)} COLLATE "C")'


def starts_with_clause(column: Any, value: str) -> ColumnElement[bool]:
    """``value <= column < successor`` in code-point order — see
    :func:`prefix_range` and :class:`ByteOrdered`."""
    low, high = prefix_range(value)
    ordered = ByteOrdered(column)
    return and_(ordered >= low, ordered < high) if high is not None else ordered >= low
