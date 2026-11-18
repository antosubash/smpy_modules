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
    event_id: uuid.UUID
    title: str
    lang: str
    calendar: MineCalendarOut
    leads: list[int]
    next_start: datetime | None


class MinePageOut(BaseModel):
    items: list[MineItemOut]
    total: int
    hidden: int
    """Followed events the caller can no longer see: counted, never named."""
    page: int
    page_size: int


class DeliveryCounts(BaseModel):
    sent: int
    failed: dict[str, int]
    """By stable code (``send_failed``, ``send_timeout``)."""
    unfinished: int


class DeliveryOut(BaseModel):
    """What a manager needs to know: counts only, never who was or was not reminded."""

    enabled: bool
    available: bool
    reason: str | None
    defaults: list[int]
    window_days: int
    counts: DeliveryCounts
