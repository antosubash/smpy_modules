"""Event responses. No input bounds: a stored row always renders."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from sm_events.web.schemas.overrides import OverrideOut
from sm_events.web.schemas.texts import TextOut


class SubEvent(BaseModel):
    id: uuid.UUID
    title: str
    start_local: str


class EventBase(BaseModel):
    id: uuid.UUID
    calendar_id: uuid.UUID
    parent_id: uuid.UUID | None
    type: str
    status: str
    scheduled: bool
    cancelled: bool
    all_day: bool
    timezone: str
    starts_at: datetime
    ends_at: datetime
    start_local: str
    end_local: str
    rrule: str | None
    category_id: uuid.UUID | None
    venue_name: str | None
    revision: int
    publish_at: datetime | None
    published_at: datetime | None
    trashed: bool = False
    can_write: bool = False
    can_publish: bool = False
    locked: bool = False


class EventListItem(EventBase):
    title: str
    lang: str


class EventPage(BaseModel):
    items: list[EventListItem]
    total: int
    page: int
    page_size: int


class EventOut(EventBase):
    uid: str
    recurrence_until: datetime | None
    publish_at_local: str | None
    attendance_mode: str
    address: str | None
    online_url: str | None
    latitude: float | None
    longitude: float | None
    organiser: str | None
    image: str | None
    registration_url: str | None
    extra: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None
    texts: dict[str, TextOut]
    overrides: list[OverrideOut]
    sub_events: list[SubEvent]


class RevisionOut(BaseModel):
    number: int
    action: str
    actor: str | None
    actor_name: str | None = None
    """The actor's display name, resolved like a calendar owner's; ``None`` for the
    beat, for a non-member and for a label that carries an address."""
    system: bool = False
    """No actor at all (the beat), as opposed to an actor whose name is unknown."""
    created_at: datetime
    note: str | None


class RevisionDetail(RevisionOut):
    snapshot: dict[str, Any]
