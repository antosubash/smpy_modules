"""SQLModel tables of the Events module.

Every table is imported here so ``Base.metadata`` is complete the moment anything
imports the package - Alembic autogenerate and the test harness rely on it. All
seven tables of PRs 1 and 2 are declared now; events, texts, overrides, revisions and
redirects get their behaviour in PR 2. PR 4 adds ``events_calendar_redirect``; PR 5 adds
``events_feed_token``, ``events_import`` and ``events_import_item``; PR 8 adds
``events_follow`` and ``events_reminder_sent``.
"""

from __future__ import annotations

from sm_events.models._base import Base
from sm_events.models.calendar import Calendar
from sm_events.models.calendar_redirect import CalendarRedirect
from sm_events.models.category import Category
from sm_events.models.enums import (
    ATTENDANCE_MODES,
    DEFAULT_EVENT_TYPE,
    EVENT_STATUSES,
    OVERRIDE_KINDS,
    EventStatus,
    OverrideKind,
    Visibility,
)
from sm_events.models.event import Event
from sm_events.models.event_text import EventText
from sm_events.models.feed_token import FeedToken
from sm_events.models.imports import EventImport, EventImportItem
from sm_events.models.occurrence_override import OccurrenceOverride
from sm_events.models.redirect import Redirect
from sm_events.models.reminders import EventFollow, ReminderSent
from sm_events.models.revision import Revision

__all__ = [
    "ATTENDANCE_MODES",
    "DEFAULT_EVENT_TYPE",
    "EVENT_STATUSES",
    "OVERRIDE_KINDS",
    "Base",
    "Calendar",
    "CalendarRedirect",
    "Category",
    "Event",
    "EventFollow",
    "EventImport",
    "EventImportItem",
    "EventStatus",
    "EventText",
    "FeedToken",
    "OccurrenceOverride",
    "OverrideKind",
    "Redirect",
    "ReminderSent",
    "Revision",
    "Visibility",
]
