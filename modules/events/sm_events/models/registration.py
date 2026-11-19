"""Registration seats (PR 9): one counter per occurrence and one row per holder.

Events owns the seats and the rule; the module that owns the people (records) owns who they are.
A seat names its holder by an opaque id (a uuid) and nothing else, so no personal data lives here.

``RegistrationCount`` is the **lock target**: the contract's admit ``UPDATE`` takes this row's
lock, and release recomputes ``taken`` from the seat rows under the same lock, so the counter is
always a function of the seats. ``RegistrationSeat`` makes admit and release idempotent per
holder: its unique key is ``(tenant, provider, holder)``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field

from sm_events.core.constants import (
    OCCURRENCE_KEY_MAX,
    REGISTRATION_HOLDER_MAX,
    REGISTRATION_PROVIDER_MAX,
    REGISTRATION_TARGET_MAX,
)
from sm_events.models._base import Base
from sm_events.models._cols import big_pk, counter, dt_col, fk_uuid

COUNT_CONSTRAINT = "uq_events_registration_count"
SEAT_CONSTRAINT = "uq_events_registration_seat"


class RegistrationCount(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_registration_count"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", "occurrence_key", name=COUNT_CONSTRAINT),
    )

    id: int | None = big_pk()
    event_id: uuid.UUID = fk_uuid("events_event.id", ondelete="CASCADE")
    occurrence_key: str = Field(max_length=OCCURRENCE_KEY_MAX)
    taken: int = counter()
    updated_at: datetime = dt_col(nullable=False)


class RegistrationSeat(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_registration_seat"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "holder", name=SEAT_CONSTRAINT),
        Index("ix_events_registration_seat_occ", "tenant_id", "event_id", "occurrence_key"),
    )

    id: int | None = big_pk()
    event_id: uuid.UUID = fk_uuid("events_event.id", ondelete="CASCADE")
    occurrence_key: str = Field(max_length=OCCURRENCE_KEY_MAX)
    provider: str = Field(max_length=REGISTRATION_PROVIDER_MAX)
    target: str = Field(max_length=REGISTRATION_TARGET_MAX)
    holder: str = Field(max_length=REGISTRATION_HOLDER_MAX)
    created_at: datetime = dt_col(nullable=False)
