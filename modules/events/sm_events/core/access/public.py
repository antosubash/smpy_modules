"""The one place that decides what the anonymous surface may see.

The public pages, the list, the API, the feeds, the sitemap, the redirects, the JSON-LD
and the 404's suggestions all start from :func:`public_events` or
:func:`public_calendars`, or from the occurrences read called with
:data:`ANONYMOUS` and ``include_unpublished=False``. Nothing builds its own predicate on
``status`` or ``visibility``, and no public handler takes a viewer from the request: a
signed-in visitor, a manager included, gets exactly the anonymous answer.

What that is: **published** events of **public** calendars, never trashed (the soft-delete
criteria reach both selects), and only the bound tenant's. The tenant predicate is
explicit as well as the framework's, and raises ``TenantUnbound`` when none is bound, so a
public read can never run unscoped.
"""

from __future__ import annotations

from typing import Any

from simple_module_core.resources import ResourcePrincipal

from sm_events.core.access import visible_calendars
from sm_events.core.access.events import visible_events
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Calendar, Event

__all__ = ["ANONYMOUS", "public_calendars", "public_events"]

ANONYMOUS = ResourcePrincipal(user_id=None, permissions=frozenset())
"""The principal of every public read: no user, no permission."""


def public_calendars() -> Any:
    """``SELECT Calendar`` of the bound tenant's public, untrashed calendars."""
    return visible_calendars(ANONYMOUS).where(Calendar.tenant_id == bound_tenant())  # type: ignore[arg-type]


def public_events() -> Any:
    """``SELECT Event`` of the bound tenant's published, untrashed events on a public,
    untrashed calendar."""
    return visible_events(ANONYMOUS, include_unpublished=False).where(
        Event.tenant_id == bound_tenant()  # type: ignore[arg-type]
    )
