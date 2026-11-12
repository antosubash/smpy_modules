"""What one anonymous listing may cost (#349).

The public listing and its stats block take the admin grammar narrowed to the
public shape (:mod:`sm_records.records.services.public`), and the admin caps
(``max_filter_terms``, 20 by default) were the only brake on it. A ``contains``
term compiles to ``ILIKE '%term%'`` over the type's text index rows, which no
index answers, so one request could ask for twenty substring scans of a large
public type — at no cost to a caller with no session, from as many addresses
as it likes.

Two bounds, both specific to this surface; the admin surface keeps its own:

* **Fewer terms.** At most :data:`PUBLIC_MAX_FILTER_TERMS` filter terms, of
  which at most :data:`PUBLIC_MAX_CONTAINS_TERMS` may be ``contains``. The
  records list and stats widgets send one term each, so no page built with
  them is anywhere near either. A refusal is a 400 in the module's
  ``{"detail", "code"}`` envelope, with a code a client can test.
* **A statement timeout** (:func:`statement_timeout`). On Postgres the listing
  runs under ``SET LOCAL statement_timeout``, which lasts until the request's
  transaction ends and so covers the page, its bounded count and the
  translation lookup after it. A cancelled statement is a 503
  ``query_timeout``, not a 500. SQLite has no such setting; the term caps are
  its bound.

Constants rather than settings: there is no install for which twenty public
substring scans in one request is the right answer, and an operator who wants
a heavier public query has the authenticated API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Final

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.records.index.query import Filter, FilterOp
from sm_records.records.services.errors import RecordsError

__all__ = [
    "PUBLIC_MAX_CONTAINS_TERMS",
    "PUBLIC_MAX_FILTER_TERMS",
    "PUBLIC_STATEMENT_TIMEOUT_MS",
    "PublicQueryRefused",
    "PublicQueryTimedOut",
    "cancelled",
    "check_public_filters",
    "statement_timeout",
    "too_many_filters",
]

PUBLIC_MAX_FILTER_TERMS: Final = 3
"""Filter terms one anonymous listing or stats request may carry."""

PUBLIC_MAX_CONTAINS_TERMS: Final = 1
"""Of those, how many may be ``contains`` (an unindexed substring scan)."""

PUBLIC_STATEMENT_TIMEOUT_MS: Final = 5000
"""Postgres ``statement_timeout`` for the public listing's transaction."""

_QUERY_CANCELED: Final = "57014"
"""Postgres' SQLSTATE for a statement cancelled by ``statement_timeout``."""


class PublicQueryRefused(RecordsError):  # noqa: N818 - HTTP vocabulary, deliberately
    """More filter terms, or more ``contains`` terms, than the public surface takes."""

    status_code = 400

    def __init__(self, detail: str, code: str) -> None:
        self.code = code
        super().__init__(detail)


class PublicQueryTimedOut(RecordsError):  # noqa: N818 - HTTP vocabulary, deliberately
    """The public listing's statement ran past :data:`PUBLIC_STATEMENT_TIMEOUT_MS`."""

    status_code = 503
    code = "query_timeout"

    def __init__(self) -> None:
        super().__init__("the query took too long; narrow the filter and try again")


def too_many_filters(sent: int) -> PublicQueryRefused:
    """The refusal for more than :data:`PUBLIC_MAX_FILTER_TERMS` terms."""
    return PublicQueryRefused(
        f"too many 'filter' terms: {sent} sent, at most "
        f"{PUBLIC_MAX_FILTER_TERMS} on the public API",
        "too_many_filters",
    )


def check_public_filters(filters: Sequence[Filter]) -> None:
    """Refuse a public request over either term cap (see the module docstring).

    The public routes also count the raw terms before parsing them
    (``_grammar.parse_public_filters``), ahead of the admin ``max_filter_terms``,
    so 25 terms are ``too_many_filters`` there too; this is the services' own
    check, for a caller that is not those routes."""
    if len(filters) > PUBLIC_MAX_FILTER_TERMS:
        raise too_many_filters(len(filters))
    contains = sum(1 for flt in filters if flt.op is FilterOp.CONTAINS)
    if contains > PUBLIC_MAX_CONTAINS_TERMS:
        raise PublicQueryRefused(
            f"too many 'contains' filter terms: {contains} sent, at most "
            f"{PUBLIC_MAX_CONTAINS_TERMS} on the public API",
            "too_many_contains",
        )


def cancelled(exc: BaseException) -> bool:
    """Whether ``exc`` is a statement Postgres cancelled (``statement_timeout``).

    ``SET LOCAL`` lasts until the transaction ends, so any query a public
    request runs after the listing (the translation lookup, the commit) can be
    the one cancelled; the records route classes map this at the handler
    boundary as well, so none of them becomes a 500."""
    if not isinstance(exc, DBAPIError):
        return False
    code = getattr(exc.orig, "pgcode", None) or getattr(exc.orig, "sqlstate", None)
    return code == _QUERY_CANCELED


@asynccontextmanager
async def statement_timeout(db: AsyncSession) -> AsyncIterator[None]:
    """Run the body under the public statement timeout, on Postgres.

    ``SET LOCAL`` takes no bound parameter, so the value is the integer
    constant spelled into the statement. A cancellation leaves the transaction
    aborted; :class:`PublicQueryTimedOut` is a ``RecordsError``, so the public
    route class rolls the session back before answering.
    """
    if db.get_bind().dialect.name != "sqlite":
        await db.execute(text(f"SET LOCAL statement_timeout = {int(PUBLIC_STATEMENT_TIMEOUT_MS)}"))
    try:
        yield
    except DBAPIError as exc:
        if not cancelled(exc):
            raise
        raise PublicQueryTimedOut() from exc
