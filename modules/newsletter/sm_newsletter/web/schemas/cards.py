"""Bodies of the card, media and card-refresh routes."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from sm_newsletter.content.blocks import UUID_RE
from sm_newsletter.content.blocks import Id as BlockId
from sm_newsletter.content.integrations.hits import MAX_SOURCE_ID


class CardHitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: Literal["article", "page"]
    source_id: int
    title: str
    excerpt: str
    image_url: str
    url: str
    locale: str


class EventHitOut(BaseModel):
    """An event the picker offers: only what the public page shows. ``source_id`` is the event's id,
    for this editor's snapshot request; nothing public carries it."""

    model_config = ConfigDict(from_attributes=True)

    kind: Literal["event"]
    source_id: str
    title: str
    excerpt: str
    image_url: str
    url: str
    ics_url: str
    locale: str
    starts_at: datetime
    ends_at: datetime
    all_day: bool
    start_date: date | None
    end_date: date | None
    timezone: str
    attendance_mode: str
    place: str
    cancelled: bool
    when: str = ""
    """The date and time as the email words them (the event's zone, its abbreviation), so the
    picker, the preview and the email agree."""


class MediaHitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    url: str


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["article", "page"]
    source_id: Annotated[StrictInt, Field(gt=0, le=MAX_SOURCE_ID)]


class EventSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["event"]
    source_id: Annotated[str, Field(pattern=UUID_RE)]


def snapshot_model(payload: object) -> type[SnapshotRequest] | type[EventSnapshotRequest]:
    """The request model for ``payload``'s ``kind``, so an error still names the field."""
    if isinstance(payload, dict) and payload.get("kind") == "event":
        return EventSnapshotRequest
    return SnapshotRequest


class CardSnapshot(BaseModel):
    """A card block's props, ready to drop into the body."""

    id: str
    source_id: int
    title: str
    excerpt: str
    image_url: str
    url: str
    locale: str
    snapshot_at: datetime


class EventCardSnapshot(BaseModel):
    """An event card block's props, ready to drop into the body."""

    id: str
    source_id: str
    title: str
    excerpt: str
    image_url: str
    url: str
    ics_url: str
    locale: str
    starts_at: datetime
    ends_at: datetime
    all_day: bool
    start_date: date | None
    end_date: date | None
    timezone: str
    attendance_mode: Literal["in_person", "online", "hybrid"]
    place: str
    cancelled: bool
    snapshot_at: datetime


class RefreshRequest(BaseModel):
    """``expected_revision`` is the revision the editor read (409 ``stale``)."""

    model_config = ConfigDict(extra="forbid")

    block_id: BlockId
    expected_revision: StrictInt
