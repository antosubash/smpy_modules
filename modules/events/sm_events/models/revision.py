"""One saved state of an event, for history and restore."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from sm_events.core.constants import NOTE_MAX
from sm_events.models._base import Base
from sm_events.models._cols import big_pk, dt_col, fk_uuid, json_col


class Revision(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_revision"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", "number", name="uq_events_revision_number"),
    )

    id: int | None = big_pk()
    event_id: uuid.UUID = fk_uuid("events_event.id", ondelete="CASCADE")
    number: int
    action: str = Field(max_length=24)
    actor: str | None = Field(default=None, max_length=255)
    snapshot: dict[str, Any] = json_col(dict)
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    """A reject note, or the overrides a series change dropped."""
    created_at: datetime = dt_col(nullable=False)
