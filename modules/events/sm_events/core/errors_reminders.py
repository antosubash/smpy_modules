"""The refusals of reminders (PR 8).

Kept beside :mod:`sm_events.core.errors` (which is near the file-size cap); they are
:class:`EventsError` subclasses, so the one installed handler renders them.
"""

from __future__ import annotations

from sm_events.core import constants
from sm_events.core.errors import Conflict, Invalid, ServiceUnavailable

__all__ = ["FollowLimit", "InvalidLead", "NotPublished", "RemindersUnavailable"]


class FollowLimit(Conflict):
    """The user already follows the most events one account may."""

    code = constants.FOLLOW_LIMIT_CODE
    detail = constants.FOLLOW_LIMIT_DETAIL


class NotPublished(Conflict):
    """A writer who can see an unpublished event: nothing leaks, but it cannot be followed."""

    code = constants.NOT_PUBLISHED_CODE
    detail = constants.NOT_PUBLISHED_DETAIL


class InvalidLead(Invalid):
    code = constants.INVALID_LEAD_CODE
    detail = constants.INVALID_LEAD_DETAIL


class RemindersUnavailable(ServiceUnavailable):
    """Mail cannot be delivered (or is off): nobody is promised a reminder that cannot arrive."""

    code = constants.REMINDERS_UNAVAILABLE_CODE
    detail = constants.REMINDERS_UNAVAILABLE_DETAIL
