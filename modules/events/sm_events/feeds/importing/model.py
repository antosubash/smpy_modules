"""What an import item's payload holds: one event as the module's validators expect it."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from sm_events.web.schemas.events_in import TimesIn

__all__ = ["MappedEvent", "MappedOverride"]


class MappedOverride(BaseModel):
    original_start: datetime
    """The occurrence's start as a UTC instant, exactly as the module stores it."""
    kind: Literal["skipped", "cancelled", "moved"]
    start: str | None = None
    end: str | None = None
    """A moved occurrence's new local times, in the series' zone."""


class MappedEvent(BaseModel):
    """Stored as JSON on the item (``payload``) and read back by the apply step."""

    uid: str
    times: TimesIn
    rrule: str | None
    cancelled: bool
    attendance_mode: str
    venue_name: str | None
    online_url: str | None
    url: str | None = None
    """The VEVENT's own ``URL`` when it is a web address (subscriptions link to it; the import
    ignores it: its description already carries the link)."""
    latitude: float | None
    longitude: float | None
    category_id: uuid.UUID | None
    title: str
    description: str
    private_class: bool
    overrides: list[MappedOverride]
