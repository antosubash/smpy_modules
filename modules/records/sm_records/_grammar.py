"""The query-string grammar: ``?filter=``, ``?sort=`` and ``?expand=``.

Split from :mod:`sm_records.deps` for the 300-line cap, along a seam that was
already in that module's docstring: everything here parses a *query string*
and none of it touches the request's identity, its session or the database.
The API and the record-list view both depend on these, which is what makes a
deep link into the admin UI show exactly what the same query would return
from the JSON API.

Re-exported from ``deps``, so every endpoint keeps importing one module.
"""

from __future__ import annotations

from typing import Any, Final, NamedTuple

from fastapi import HTTPException, Query

from sm_records import constants
from sm_records.index.query import Filter, FilterOp, Sort

__all__ = [
    "MALFORMED_FILTER",
    "PageCursor",
    "parse_cursor",
    "parse_expand",
    "parse_filters",
    "parse_sorts",
    "parse_view_filters",
]


def _parse_filter(raw: str) -> Filter:
    """``field:op:value``, split on the first two colons — a value carrying
    its own colon (a URL, a timestamp) must not be truncated by it."""
    parts = raw.split(":", 2)
    if len(parts) != 3:
        raise HTTPException(
            status_code=400, detail=f"invalid filter {raw!r}: expected 'field:op:value'"
        )
    field, op_raw, value = parts
    try:
        op = FilterOp(op_raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"invalid filter {raw!r}: unknown operator {op_raw!r}"
        ) from exc
    parsed_value: Any
    if op is FilterOp.IN:
        parsed_value = value.split(",")
    elif op is FilterOp.IS_NULL:
        low = value.strip().lower()
        if low not in ("true", "false"):
            raise HTTPException(
                status_code=400,
                detail=f"invalid filter {raw!r}: is_null takes 'true' or 'false'",
            )
        parsed_value = low == "true"
    else:
        parsed_value = value
    return Filter(field=field, op=op, value=parsed_value)


def parse_filters(raw_filters: list[str] = Query(default=[], alias="filter")) -> list[Filter]:
    """``?filter=`` repeats; each is one term, ANDed together."""
    return [_parse_filter(item) for item in raw_filters]


MALFORMED_FILTER: Final = "malformed"
"""The ``errors["filter"]`` reason a view reports for a filter term that does
not parse, alongside ``QueryError.reason``'s ``unknown``/``not_indexed``/
``reindexing``."""


def parse_view_filters(
    raw_filters: list[str] = Query(default=[], alias="filter"),
) -> tuple[list[Filter], str | None]:
    """:func:`parse_filters` for a *page navigation*, which cannot 400.

    ``_parse_filter`` raises ``HTTPException(400)`` from inside a dependency,
    so it escapes before the view handler runs and Inertia shows a bare error
    modal — for a deep link with a typo'd ``?filter=``, on the one screen that
    already has an ``errors`` bag for a filter it refuses. The parse failure
    is returned as a reason instead, and the handler renders the list empty
    with the notice, exactly as it does for ``unknown``/``not_indexed``.
    """
    try:
        return [_parse_filter(item) for item in raw_filters], None
    except HTTPException:
        return [], MALFORMED_FILTER


def parse_expand(
    raw_expand: list[str] = Query(default=[], alias=constants.EXPAND_PARAM),
) -> list[str]:
    """``?expand=a,b`` (and ``?expand=a&expand=b``) — the relation fields to
    resolve on this read, design §9.

    Both spellings, because both are what a client reaches for and neither is
    ambiguous: the grammar is a list of field keys, and a field key cannot
    contain a comma (``TYPE_KEY_PATTERN``). Order is preserved and duplicates
    are dropped here rather than in the service, so ``expand=a,a`` cannot cost
    two queries.

    No validation of the keys themselves: whether a key names a relation field
    is a question about the *type*, which this dependency cannot see — it is
    ``services.expand``'s, and it answers with the same ``QueryError`` the
    filter grammar refuses an unknown field with.
    """
    keys: list[str] = []
    for raw in raw_expand:
        for item in raw.split(","):
            key = item.strip()
            if key and key not in keys:
                keys.append(key)
    return keys


def parse_sorts(raw_sorts: list[str] = Query(default=[], alias="sort")) -> list[Sort]:
    """``?sort=`` repeats; a leading ``-`` means descending."""
    return [
        Sort(field=item[1:], desc=True) if item.startswith("-") else Sort(field=item, desc=False)
        for item in raw_sorts
    ]


class PageCursor(NamedTuple):
    """``?after=`` and ``?total=``, parsed — the two knobs of F11 and F4.

    Carried as one object rather than two parameters because the refusal
    below is about their *combination* with ``?page=``, and a dependency that
    sees only one of them cannot make it.
    """

    after: str | None
    with_total: bool


def parse_cursor(
    page: int = Query(default=1, ge=1),
    after: str | None = Query(default=None),
    total: bool = Query(default=True),
) -> PageCursor:
    """``?after=<cursor>`` pages by keyset; ``?page=`` still pages by offset.

    Sending both is a 400 rather than a precedence rule. They answer the same
    question differently — "the 200th page of this order" against "whatever
    follows this row" — and a caller that sent both has a bug the server
    cannot resolve in its favour: silently honouring one would hand back a
    page that is correct for a request nobody made.

    ``?total=false`` drops the count statement entirely (``total: null``,
    ``total_capped: false``), which is what a caller walking the type with
    ``after`` should send — it is otherwise paying for a number it never
    reads, on every page.
    """
    if after is not None and page != 1:
        raise HTTPException(
            status_code=400,
            detail="send either 'page' or 'after', not both: they are two ways to ask for a page",
        )
    return PageCursor(after=after, with_total=total)
