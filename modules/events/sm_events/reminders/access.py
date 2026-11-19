"""Would a reminder reach this user? Asked in the *request*, where everything is known.

A worker works out access with the offline principal, which can hold less than the request
principal the user is acting as (the membership role has no public read, upstream #1005). The
follow is still stored, but the user must not wait for mail that will never come. So when a
follow is read or written the same send-time check
(:func:`~sm_events.reminders.recipients.eligible`, through the live app) is run for that
user, and the answer rides in the response (``deliverable`` and the code
``reminders_no_access``); the Reminders page shows it per row.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from typing import Any

from simple_module_core.resources import ResourcePrincipal

from sm_events.core.tenancy import bound_tenant
from sm_events.reminders.recipients import eligible
from sm_events.reminders.runtime import web_runtime

__all__ = ["deliverable"]


async def deliverable(
    app: Any, db: Any, who: ResourcePrincipal, event_ids: Collection[uuid.UUID]
) -> set[uuid.UUID]:
    """Of ``event_ids``, the events a reminder could still be sent to ``who`` for, right now."""
    if who.user_id is None or not event_ids:
        return set()
    found = await eligible(
        db, web_runtime(app), tenant_id=bound_tenant(), wanted={who.user_id: set(event_ids)}
    )
    got = found.allowed.get(who.user_id)
    return got[1] if got is not None else set()
