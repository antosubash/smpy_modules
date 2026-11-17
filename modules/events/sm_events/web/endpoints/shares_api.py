"""The share dialog's user picker.

The framework has no share UI, so events builds one against
``/api/sharing/shares`` and needs a way to find a grantee. This is it: owner or
``events.manage`` only (``CalendarOwner``, so an edit share is a 403), names come
from the framework's ``UserDirectory``, and on a multi-tenant host only members
of the bound tenant are offered - the picker must not reveal accounts of other
organisations. Grants, lists and revokes go through the framework's own
``/api/sharing/shares`` with ``resource_type="events.calendar"``; events adds no
share routes of its own.

**Not a directory listing.** On a single-tenant host there is no membership to
filter by, and anyone who can create a calendar owns one, so an empty or
one-letter ``q`` would page through every active account's name and address. A
query shorter than :data:`MIN_QUERY` characters (after trimming) answers ``[]``
without asking the directory, and the route has its own per-user rate
(:data:`RATE`, registered by ``EventsModule.register_rate_limits``) so the
remaining three-letter space cannot be walked quickly either.

**Not an email oracle.** The directory matches on email substrings, so the
answer is filtered (:func:`matches_query`) before the limit: a user is offered
only when the query is part of their display name, or is their whole address.
A partial address finds nobody, so an address cannot be confirmed piece by piece.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Depends, Query, Request
from simple_module_db.deps import get_db

from sm_events.core import constants
from sm_events.core.access import CalendarOwner
from sm_events.web.endpoints.deps import require_view
from sm_events.web.schemas.shares import ShareCandidate
from sm_events.web.services.masking import matches_query, safe_display_name, visible_email
from sm_events.web.services.members import directory_or_unavailable, members_only

MIN_QUERY: Final = 3
"""Characters of ``q`` (trimmed) below which the picker answers nobody."""
RATE: Final = "60/minute"
"""Per signed-in user, through the framework's rate-limit middleware."""
PATH_PATTERN: Final = rf"^{constants.ROUTE_PREFIX_API}/calendars/[^/]+/share-candidates$"
"""The route, as the rate-limit rule matches it."""

router = APIRouter(prefix="/calendars", tags=["shares"])


@router.get("/{calendar_id}/share-candidates", dependencies=[require_view])
async def share_candidates(
    request: Request,
    calendar: CalendarOwner,
    q: str = Query("", max_length=100),
    db=Depends(get_db),
) -> list[ShareCandidate]:
    directory = directory_or_unavailable(request)
    term = q.strip()
    if len(term) < MIN_QUERY:
        return []
    found = await directory.search(db, term, limit=constants.CANDIDATES_SCAN)
    users = [
        u
        for u in found
        if u.is_active and u.id != calendar.owner_id and matches_query(u.label, u.email, term)
    ]
    users = await members_only(request, db, users)
    return [
        ShareCandidate(
            id=u.id,
            display_name=safe_display_name(u.label, u.email, term),
            email=visible_email(u.email, term),
        )
        for u in users[: constants.CANDIDATES_MAX]
    ]
