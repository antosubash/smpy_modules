"""Who may see or act on a calendar, and so on everything inside it.

One policy object, :data:`POLICY`, answers every question: list and count
statements go through :meth:`CalendarPolicy.filter`, a single row through
``RequiresResource`` (:data:`CalendarView` and friends), and the ``sharing``
module through the ``events.calendar`` resource type. Every later read of an
event goes through it too.

``M`` is ``events.manage``, ``V`` is ``events.view``, ``signed`` is a signed-in
principal, and a share is a row in ``sharing``'s table (view or edit, never
expired):

==============  ==============================================================
action          who
==============  ==============================================================
view            ``M``; else, with ``V`` and signed in: the owner, a view or
                edit share, ``internal`` and ``public``. Without ``V`` (or
                anonymous): ``public`` only
edit            ``M``; with ``V`` and signed in: the owner, an edit share
                (the calendar's own metadata; never ``events.edit`` alone)
delete, share   ``M``; with ``V`` and signed in: the owner (shares never)
write_events    ``M``; with ``V`` and signed in: the owner, an edit share, or
                ``events.edit`` on an ``internal`` or ``public`` calendar
==============  ==============================================================

A principal who lost ``events.view`` (an owner, a share holder) therefore gets
what an anonymous one gets, so the framework's sharing router, which needs only
``sharing.share``, cannot be used to read a calendar around it.

**No tenant predicate here.** Calendars and shares carry ``MultiTenantMixin``;
``bind_admin`` binds the tenant and the framework filters on it. That binding is
also what makes ``internal`` mean "a member of this tenant".
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sharing.core.policy import share_exists_for
from simple_module_core.permission_denied import PermissionDenied
from simple_module_core.resources import (
    ACTION_DELETE,
    ACTION_EDIT,
    ACTION_SHARE,
    ACTION_VIEW,
    ResourcePrincipal,
)
from simple_module_hosting.resource_deps import RequiresResource
from sqlalchemy import false, or_
from sqlmodel import select

from sm_events.core import constants
from sm_events.core.errors import Forbidden, NotFound, OwnerRequired
from sm_events.models import Calendar, Visibility

CALENDAR_RESOURCE = "events.calendar"
"""The ``sharing`` resource type, and ``ResourceShare.resource_type``."""

ACTION_WRITE_EVENTS = "write_events"
"""Module-internal: whether events may be written in the calendar (PR 2)."""

_MEMBER_VISIBILITY = (Visibility.INTERNAL.value, Visibility.PUBLIC.value)


class CalendarPolicy:
    """The framework's ``ResourcePolicy`` protocol, for :class:`Calendar`."""

    def __init__(self) -> None:
        self._shares = share_exists_for(CALENDAR_RESOURCE, Calendar.id)

    def _share(self, who: ResourcePrincipal, action: str) -> Any:
        # A share grants view or edit and nothing else (a future sharing role
        # implying more must not widen calendars).
        if action not in (ACTION_VIEW, ACTION_EDIT):
            return None
        return self._shares(who, action)

    def predicate(self, who: ResourcePrincipal, action: str) -> Any:
        """The ``WHERE`` clause, or ``None`` when the principal bypasses it."""
        if who.has(constants.PERM_MANAGE):
            return None
        public = Calendar.visibility == Visibility.PUBLIC.value
        if who.user_id is None or not who.has(constants.PERM_VIEW):
            return public if action == ACTION_VIEW else false()
        owner = Calendar.owner_id == who.user_id
        member_visible = Calendar.visibility.in_(_MEMBER_VISIBILITY)
        clauses: list[Any] = [owner]
        if action == ACTION_VIEW:
            clauses += [self._share(who, ACTION_VIEW), member_visible]
        elif action == ACTION_EDIT:
            clauses.append(self._share(who, ACTION_EDIT))
        elif action == ACTION_WRITE_EVENTS:
            clauses.append(self._share(who, ACTION_EDIT))
            if who.has(constants.PERM_EDIT):
                clauses.append(member_visible)
        elif action not in (ACTION_DELETE, ACTION_SHARE):
            return false()
        return or_(*(c for c in clauses if c is not None))

    def filter(self, who: ResourcePrincipal, action: str, stmt: Any) -> Any:
        clause = self.predicate(who, action)
        return stmt if clause is None else stmt.where(clause)

    def can(self, who: ResourcePrincipal, action: str, obj: Any) -> bool:
        """The predicate in Python, for a loaded row. A share is a row this
        cannot see, so it never answers yes for one (``load_authorized`` then
        asks :meth:`filter`)."""
        if who.has(constants.PERM_MANAGE):
            return True
        public = obj.visibility == Visibility.PUBLIC.value
        if who.user_id is None or not who.has(constants.PERM_VIEW):
            return action == ACTION_VIEW and public
        if obj.owner_id == who.user_id and action in (
            ACTION_VIEW,
            ACTION_EDIT,
            ACTION_DELETE,
            ACTION_SHARE,
            ACTION_WRITE_EVENTS,
        ):
            return True
        member_visible = obj.visibility in _MEMBER_VISIBILITY
        if action == ACTION_VIEW:
            return member_visible
        return action == ACTION_WRITE_EVENTS and who.has(constants.PERM_EDIT) and member_visible


POLICY = CalendarPolicy()


def visible_calendars(who: ResourcePrincipal, action: str = ACTION_VIEW) -> Any:
    """``SELECT Calendar`` narrowed to what *who* may *action* (trash excluded)."""
    return POLICY.filter(who, action, select(Calendar))


def calendar_stmt(calendar_id: uuid.UUID) -> Any:
    """The unfiltered loader ``RequiresResource`` narrows through :data:`POLICY`."""
    return select(Calendar).where(Calendar.id == calendar_id)


class _Requires(RequiresResource):
    """``RequiresResource`` whose refusals use events' ``{"detail", "code"}``
    envelope: a 404 for a calendar the caller cannot see, a 403 ``forbidden``
    for one they can see but not change, and ``owner_required`` for an
    owner-only action (naming who may act, not the internal ``resource:delete``)."""

    def __init__(self, action: str, *, owner: bool = False) -> None:
        super().__init__(POLICY, action, calendar_stmt)
        self._owner = owner

    async def __call__(self, *, request: Request, stmt: Any, session: Any) -> Any:
        try:
            return await super().__call__(request=request, stmt=stmt, session=session)
        except PermissionDenied:
            if self._owner:
                raise OwnerRequired(constants.OWNER_ONLY_DETAIL) from None
            raise Forbidden(constants.EDIT_REFUSED_DETAIL) from None
        except HTTPException as exc:
            if exc.status_code == 404:
                raise NotFound(constants.NOT_FOUND_DETAIL) from None
            raise


# No ``permission=``: an API token is refused on these routes until a route
# opts in by building its own ``RequiresResource(..., permission=...)``.
CalendarView = Annotated[Calendar, Depends(_Requires(ACTION_VIEW))]
CalendarEdit = Annotated[Calendar, Depends(_Requires(ACTION_EDIT))]
CalendarOwner = Annotated[Calendar, Depends(_Requires(ACTION_DELETE, owner=True))]
"""Owner or ``events.manage``: visibility, delete, shares, ownership."""

__all__ = [
    "ACTION_WRITE_EVENTS",
    "CALENDAR_RESOURCE",
    "POLICY",
    "CalendarEdit",
    "CalendarOwner",
    "CalendarPolicy",
    "CalendarView",
    "calendar_stmt",
    "visible_calendars",
]
