"""The access matrix's cast: three calendars, shares, and principals to ask as."""

from __future__ import annotations

from typing import Any

from sharing.core.policy import canonical_id
from sharing.models import ResourceShare
from simple_module_core.resources import ResourcePrincipal
from sm_events.core.access import CALENDAR_RESOURCE
from sm_events.models import Calendar, Visibility

OWNER = "o"
VIEW_SHARE = "sv"
EDIT_SHARE = "se"


def principal(user_id: str | None, *perms: str) -> ResourcePrincipal:
    return ResourcePrincipal(user_id=user_id, permissions=frozenset(perms))


def share(calendar: Calendar, user_id: str, role: str, **kw: Any) -> ResourceShare:
    return ResourceShare(
        resource_type=CALENDAR_RESOURCE,
        resource_id=canonical_id(calendar.id),
        subject_type="user",
        subject_id=user_id,
        role=role,
        granted_by=OWNER,
        **kw,
    )


async def seed_calendars(db: Any) -> dict[str, Calendar]:
    """``P`` (private), ``I`` (internal) and ``U`` (public), all owned by ``o``.
    User ``sv`` holds a view share and ``se`` an edit share on all three."""
    cals = {
        letter: Calendar(slug=slug, name=slug, owner_id=OWNER, visibility=visibility)
        for letter, slug, visibility in (
            ("P", "private", Visibility.PRIVATE),
            ("I", "internal", Visibility.INTERNAL),
            ("U", "public", Visibility.PUBLIC),
        )
    }
    db.add_all(cals.values())
    await db.flush()
    for cal in cals.values():
        db.add(share(cal, VIEW_SHARE, "view"))
        db.add(share(cal, EDIT_SHARE, "edit"))
    await db.flush()
    return cals
