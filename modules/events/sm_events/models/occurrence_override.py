"""An exception to one occurrence of a recurring series."""

from __future__ import annotations

import uuid
from datetime import datetime

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from sm_events.models._base import Base
from sm_events.models._cols import big_pk, dt_col, dt_required, fk_uuid


class OccurrenceOverride(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_occurrence_override"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "event_id", "original_start", name="uq_events_occurrence_override"
        ),
    )

    id: int | None = big_pk()
    event_id: uuid.UUID = fk_uuid("events_event.id", ondelete="CASCADE")
    original_start: datetime = dt_required()
    kind: str = Field(max_length=16)
    starts_at: datetime | None = dt_col()
    ends_at: datetime | None = dt_col()
    """``starts_at`` and ``ends_at`` are set only for ``moved``."""
    note: str | None = Field(default=None, max_length=1000)
