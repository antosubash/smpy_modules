"""A slug an event used to have, so an old link still lands."""

from __future__ import annotations

import uuid
from datetime import datetime

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from sm_events.core.constants import LOCALE_MAX, TEXT_SLUG_MAX
from sm_events.models._base import Base
from sm_events.models._cols import big_pk, dt_col, fk_uuid


class Redirect(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_redirect"
    __table_args__ = (
        UniqueConstraint("tenant_id", "locale", "old_slug", name="uq_events_redirect"),
    )

    id: int | None = big_pk()
    locale: str = Field(max_length=LOCALE_MAX)
    old_slug: str = Field(max_length=TEXT_SLUG_MAX)
    event_id: uuid.UUID = fk_uuid("events_event.id", ondelete="CASCADE")
    created_at: datetime = dt_col(nullable=False)
