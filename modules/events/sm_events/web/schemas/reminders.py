"""Reminder request bodies (bounded) and responses (not, and never anyone else's data)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, StrictInt

from sm_events.reminders.leads import LEADS_INPUT_MAX


class FollowIn(BaseModel):
    """The whole set of lead times the caller wants on one event; empty stops reminding.
    Which values are allowed is the service's call (422 ``invalid_lead``)."""

    leads: list[StrictInt] = Field(max_length=LEADS_INPUT_MAX)


class FollowOut(BaseModel):
    leads: list[int]
    defaults: list[int]
    """What "Remind me" preselects on this event's calendar."""
    next_due: dict[int, datetime | None]
    """Per chosen lead, when its next reminder is due (``null``: too late for the next one)."""
    deliverable: bool = True
    """False when the send-time check would refuse this user for this event (their rights are
    not ones a worker can read). The follow is kept; no mail would come."""
    code: str | None = None
    """``reminders_no_access`` while ``deliverable`` is false."""


class StatusOut(BaseModel):
    """Whether reminders can be delivered. ``reason`` is sent to managers only, and only while
    they cannot."""

    available: bool
    reason: str | None = None
    leads: list[int]


class MineCalendarOut(BaseModel):
    id: uuid.UUID
    name: str
    color: str


class MineItemOut(BaseModel):
    follow_id: uuid.UUID
    """The handle ``DELETE /reminders/follows/{follow_id}`` takes."""
    hidden: bool = False
    """An event the caller can no longer see: every field below is then empty."""
    event_id: uuid.UUID | None = None
    title: str | None = None
    lang: str | None = None
    calendar: MineCalendarOut | None = None
    leads: list[int] = []
    next_start: datetime | None = None
    deliverable: bool = True


class DeliveryCounts(BaseModel):
    sent: int
    failed: dict[str, int]
    """By stable code (``send_failed``, ``send_timeout``)."""
    unfinished: int


class MinePageOut(BaseModel):
    items: list[MineItemOut]
    total: int
    hidden: int
    """Followed events the caller can no longer see; each is an opaque row after the others."""
    page: int
    page_size: int
    counts: DeliveryCounts
    """The caller's own counts for the last 30 days: nobody else's."""


class DeliveryOut(BaseModel):
    """What a manager needs to know: counts only, never who was or was not reminded."""

    enabled: bool
    available: bool
    reason: str | None
    defaults: list[int]
    window_days: int
    counts: DeliveryCounts
