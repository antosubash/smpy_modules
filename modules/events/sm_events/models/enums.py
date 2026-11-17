"""Values stored as ``VARCHAR`` and validated in Python.

Never a Postgres enum: adding a value needs no migration and no enum drop on
downgrade (newsletter's ruling).
"""

from __future__ import annotations

from enum import StrEnum


class Visibility(StrEnum):
    PRIVATE = "private"
    INTERNAL = "internal"
    PUBLIC = "public"


EVENT_STATUSES = ("draft", "in_review", "published")
ATTENDANCE_MODES = ("in_person", "online", "hybrid")
OVERRIDE_KINDS = ("skipped", "cancelled", "moved")
DEFAULT_EVENT_TYPE = "event"


class EventStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    PUBLISHED = "published"
