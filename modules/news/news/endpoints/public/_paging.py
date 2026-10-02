"""Reading ``?page=`` on a route a person, not a client, arrives at.

Declared as ``Query(1, ge=1)`` the parameter answered ``?page=0``, ``?page=-1``
and ``?page=abc`` with a 422 validation error — JSON a browser renders as a
blank error page on an address a reader typed or a stale bookmark carried. This
is the same reasoning ``MAX_QUERY_LEN`` applies to ``?q=``: a public HTML route
has no way to show a validation error, so it repairs the input instead.

* missing, unparsable or below 1 — page 1, which is what the reader meant;
* absurdly large — 404, like any page past the end. Bounded *before* the
  database is asked, because an unbounded integer becomes an ``OFFSET`` the
  driver cannot bind and the answer would be a 500.
"""

from __future__ import annotations

from fastapi import HTTPException, Query

MAX_PAGE = 1_000_000
"""The largest page number worth asking the database about.

At twelve per page that is twelve million articles; anything beyond it is not a
page that exists, and 404 is the same answer a smaller out-of-range page gets.
"""


def page_param(page: str | None = Query(None)) -> int:
    """The requested page as a positive integer, leniently."""
    try:
        number = int((page or "").strip())
    except ValueError:
        return 1
    if number < 1:
        return 1
    if number > MAX_PAGE:
        raise HTTPException(status_code=404, detail="No such page")
    return number
