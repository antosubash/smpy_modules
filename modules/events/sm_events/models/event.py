"""An event, or the master of a recurring series. Behaviour arrives in PR 2."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from simple_module_db.mixins import AuditMixin, MultiTenantMixin, SoftDeleteMixin
from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field

from sm_events.core.constants import TZ_MAX
from sm_events.models._base import Base
from sm_events.models._cols import dt_col, dt_required, fk_uuid, flag, json_col, pk_uuid
from sm_events.models.enums import DEFAULT_EVENT_TYPE


class Event(Base, AuditMixin, SoftDeleteMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_event"
    __table_args__ = (
        UniqueConstraint("tenant_id", "calendar_id", "uid", name="uq_events_event_uid"),
        Index("ix_events_event_range", "tenant_id", "calendar_id", "starts_at"),
        # The recurrence prefilter: rrule IS NOT NULL AND
        # (recurrence_until IS NULL OR recurrence_until >= :start).
        Index("ix_events_event_series", "tenant_id", "calendar_id", "recurrence_until"),
        # PR 2's publish beat, read across tenants.
        Index("ix_events_event_publish_due", "status", "publish_at"),
    )

    id: uuid.UUID = pk_uuid()
    uid: str = Field(max_length=255)
    calendar_id: uuid.UUID = fk_uuid("events_calendar.id", ondelete="CASCADE")
    parent_id: uuid.UUID | None = fk_uuid("events_event.id", nullable=True, ondelete="CASCADE")
    type: str = Field(default=DEFAULT_EVENT_TYPE, max_length=64)
    status: str = Field(default="draft", max_length=16)
    cancelled: bool = flag()
    all_day: bool = flag()
    starts_at: datetime = dt_required()
    ends_at: datetime = dt_required()
    timezone: str = Field(max_length=TZ_MAX)
    rrule: str | None = Field(default=None, max_length=1000)
    recurrence_until: datetime | None = dt_col()
    attendance_mode: str = Field(default="in_person", max_length=16)
    venue_name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    online_url: str | None = Field(default=None, max_length=2048)
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)
    category_id: uuid.UUID | None = fk_uuid(
        "events_category.id", nullable=True, ondelete="SET NULL"
    )
    organiser: str | None = Field(default=None, max_length=200)
    image: str | None = Field(default=None, max_length=2048)
    registration_url: str | None = Field(default=None, max_length=2048)
    extra: dict[str, Any] = json_col(dict)
    revision: int = Field(default=1, sa_column_kwargs={"nullable": False})
    publish_at: datetime | None = dt_col()
    published_at: datetime | None = dt_col()
