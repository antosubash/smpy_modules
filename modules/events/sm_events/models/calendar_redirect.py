"""A slug a calendar used to have, so an old link or a subscription still lands."""

from __future__ import annotations

import uuid
from datetime import datetime

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from sm_events.core.constants import SLUG_MAX
from sm_events.models._base import Base
from sm_events.models._cols import big_pk, dt_col, fk_uuid

CALENDAR_REDIRECT_CONSTRAINT = "uq_events_calendar_redirect"


class CalendarRedirect(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_calendar_redirect"
    __table_args__ = (UniqueConstraint("tenant_id", "old_slug", name=CALENDAR_REDIRECT_CONSTRAINT),)

    id: int | None = big_pk()
    old_slug: str = Field(max_length=SLUG_MAX)
    calendar_id: uuid.UUID = fk_uuid("events_calendar.id", ondelete="CASCADE")
    created_at: datetime = dt_col(nullable=False)
