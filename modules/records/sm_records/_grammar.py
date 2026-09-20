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

from fastapi import Depends, HTTPException, Query, Request

from sm_records import constants
from sm_records.index.query import Filter, FilterOp, Sort
from sm_records.settings import RecordsSettings

__all__ = [
    "MALFORMED_FILTER",
    "MAX_PAGE",
    "PageCursor",
    "parse_cursor",
    "parse_expand",
    "parse_filters",
    "parse_sorts",
    "parse_view_filters",
]

MAX_PAGE: Final = 1_000_000
"""Largest ``?page=`` any listing accepts.

Not a setting, because there is no install this is a policy decision for: an
``OFFSET`` this deep has already walked and discarded more rows than
``max_count`` will even count, so the page beyond it is empty on every type
anybody has — and the caller who genuinely wants to walk that far is the one
``?after=`` exists for (F11). What it stops is the arithmetic: the offset is
``(page - 1) * page_size``, and ``page=2**63`` made that a Python integer no
SQLite binding can hold, which is an ``OverflowError`` inside the driver and a
``500`` to an anonymous caller.

Spelled as ``le=`` on the parameter rather than checked in the body, so it is
in the OpenAPI schema and refused exactly as ``page=0`` already is — one
``422`` from FastAPI's own validation, before a handler runs.

The tighter refusal — "``page * page_size`` is past ``max_count``, send
``?after=`` instead" — is deliberately not here: ``page_size`` is each
route's own parameter (and each route clamps it with
``settings.clamp_page_size``), so this dependency cannot see the number that
would make the product mean anything. A flat ceiling is the part that is
true of every listing.
"""


def _settings(request: Request) -> RecordsSettings:
    """``deps.get_settings``, imported at call time.

    :mod:`sm_records.deps` imports *this* module (it re-exports the grammar),
    so naming it at module scope would be a cycle. One accessor and not a
    second copy of ``request.app.state.sm_records.settings``: the caps below
    are settings-screen values like every other, and a stale second reader is
    how a limit starts depending on which dependency asked.
    """
    from sm_records.deps import get_settings

    return get_settings(request)


def _too_many(parameter: str, sent: int, cap: int) -> HTTPException:
    """The refusal every cap in this module raises — a 400 naming the
    *parameter*, because the caller's next move is to send fewer of them and
    nothing else in the request is wrong."""
    return HTTPException(
        status_code=400,
        detail=f"too many {parameter!r} terms: {sent} sent, at most {cap}",
    )


def _parse_filter(raw: str, settings: RecordsSettings) -> Filter:
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
        # Every value is one more bound parameter in one ``IN`` clause, and
        # the list is free to write: 2 000 of them is
        # ``Expression tree is too large`` from SQLite — a 500 on the
        # anonymous surface — and a scan on anything that survives it. The
        # importer bounds the same clause for the same reason
        # (``services._import_match``).
        if len(parsed_value) > settings.max_in_values:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"invalid filter {raw!r}: 'in' takes at most "
                    f"{settings.max_in_values} values, {len(parsed_value)} sent"
                ),
            )
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


def parse_filters(
    raw_filters: list[str] = Query(default=[], alias="filter"),
    settings: RecordsSettings = Depends(_settings),
) -> list[Filter]:
    """``?filter=`` repeats; each is one term, ANDed together.

    **Bounded by ``max_filter_terms``.** Each term is another correlated
    ``EXISTS`` over an index table, so the cost of a listing is linear in
    (terms x rows) and every one of them is free to the caller — on the
    anonymous API, which needs no session at all. Twenty is past any real UI
    (the record list builds one term per filter chip) and well under the
    point where the statement itself stops compiling.
    """
    if len(raw_filters) > settings.max_filter_terms:
        raise _too_many("filter", len(raw_filters), settings.max_filter_terms)
    return [_parse_filter(item, settings) for item in raw_filters]


MALFORMED_FILTER: Final = "malformed"
"""The ``errors["filter"]`` reason a view reports for a filter term that does
not parse, alongside ``QueryError.reason``'s ``unknown``/``not_indexed``/
``reindexing``."""


def parse_view_filters(
    raw_filters: list[str] = Query(default=[], alias="filter"),
    settings: RecordsSettings = Depends(_settings),
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
        if len(raw_filters) > settings.max_filter_terms:
            raise _too_many("filter", len(raw_filters), settings.max_filter_terms)
        return [_parse_filter(item, settings) for item in raw_filters], None
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


def parse_sorts(
    raw_sorts: list[str] = Query(default=[], alias="sort"),
    settings: RecordsSettings = Depends(_settings),
) -> list[Sort]:
    """``?sort=`` repeats; a leading ``-`` means descending.

    **Deduplicated by field, then bounded by ``max_sort_terms``.** Dedupe
    first and for the reason :func:`parse_expand` dedupes: a repeated term
    cannot change the order — the first occurrence of a field decides it —
    and each one is another ``LEFT JOIN`` onto an index table, so
    ``sort=title`` a hundred times was a hundred joins and
    ``at most 64 tables in a join`` from SQLite. The direction kept is the
    first one sent, because that is the one the order actually used.

    The cap then covers the terms that *are* distinct. Five is more ordering
    than any screen here offers and the point past which a sort is a table
    scan with extra steps.
    """
    sorts: list[Sort] = []
    seen: set[str] = set()
    for item in raw_sorts:
        desc = item.startswith("-")
        field = item[1:] if desc else item
        if field in seen:
            continue
        seen.add(field)
        sorts.append(Sort(field=field, desc=desc))
    if len(sorts) > settings.max_sort_terms:
        raise _too_many("sort", len(sorts), settings.max_sort_terms)
    return sorts


class PageCursor(NamedTuple):
    """``?after=`` and ``?total=``, parsed — the two knobs of F11 and F4.

    Carried as one object rather than two parameters because the refusal
    below is about their *combination* with ``?page=``, and a dependency that
    sees only one of them cannot make it.
    """

    after: str | None
    with_total: bool


def parse_cursor(
    page: int = Query(default=1, ge=1, le=MAX_PAGE),
    after: str | None = Query(default=None),
    total: bool = Query(default=True),
) -> PageCursor:
    """``?after=<cursor>`` pages by keyset; ``?page=`` still pages by offset.

    Sending both is a 400 rather than a precedence rule. They answer the same
    question differently — "the 200th page of this order" against "whatever
    follows this row" — and a caller that sent both has a bug the server
    cannot resolve in its favour: silently honouring one would hand back a
    page that is correct for a request nobody made.

    ``?page=`` is bounded above by :data:`MAX_PAGE` — see there for why the
    bound is a parameter constraint rather than a setting.

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
