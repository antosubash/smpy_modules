"""SQLModel tables of the Events module.

Every table is imported here so ``Base.metadata`` is complete the moment anything
imports the package - Alembic autogenerate and the test harness rely on it. All
seven tables of PRs 1 and 2 are declared now; events, texts, overrides,
revisions and redirects get their behaviour in PR 2.
"""

from __future__ import annotations

from sm_events.models._base import Base
from sm_events.models.calendar import Calendar
from sm_events.models.category import Category
from sm_events.models.enums import (
    ATTENDANCE_MODES,
    DEFAULT_EVENT_TYPE,
    EVENT_STATUSES,
    OVERRIDE_KINDS,
    EventStatus,
    Visibility,
)
from sm_events.models.event import Event
from sm_events.models.event_text import EventText
from sm_events.models.occurrence_override import OccurrenceOverride
from sm_events.models.redirect import Redirect
from sm_events.models.revision import Revision

__all__ = [
    "ATTENDANCE_MODES",
    "DEFAULT_EVENT_TYPE",
    "EVENT_STATUSES",
    "OVERRIDE_KINDS",
    "Base",
    "Calendar",
    "Category",
    "Event",
    "EventStatus",
    "EventText",
    "OccurrenceOverride",
    "Redirect",
    "Revision",
    "Visibility",
]
