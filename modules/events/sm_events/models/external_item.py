"""An event of a subscribed feed, cached read-only: plain text, times and a rule.

Nothing a remote can use to carry markup is kept: no description, attendees, organiser, alarms,
attachments or ``X-*`` property. ``span_start`` / ``span_end`` are a prefilter so one window
predicate serves one-off items and series alike (``span_end`` is ``NULL`` for an endless rule).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field

from sm_events.core.constants import (
    SUBSCRIPTION_ITEM_LOCATION_MAX,
    SUBSCRIPTION_ITEM_TITLE_MAX,
    SUBSCRIPTION_ITEM_URL_MAX,
    TZ_MAX,
    UID_MAX,
)
from sm_events.models._base import Base
from sm_events.models._cols import big_pk, dt_col, dt_required, fk_uuid, flag, json_col

ITEM_UID_CONSTRAINT = "uq_events_external_item_uid"
_HASH_LEN = 64
_RULE_MAX = 500


class ExternalItem(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_external_item"
    __table_args__ = (
        UniqueConstraint("tenant_id", "subscription_id", "uid", name=ITEM_UID_CONSTRAINT),
        Index("ix_events_external_item_window", "tenant_id", "subscription_id", "span_start"),
        # An id is never shown, but ``INTEGER PRIMARY KEY`` on SQLite reuses the highest one.
        {"sqlite_autoincrement": True},
    )

    id: int | None = big_pk()
    subscription_id: uuid.UUID = fk_uuid("events_subscription.id", ondelete="CASCADE")
    uid: str = Field(max_length=UID_MAX)

    all_day: bool = flag()
    starts_at: datetime = dt_required()
    ends_at: datetime = dt_required()
    """UTC; an all-day item follows PR 2's convention."""
    timezone: str = Field(max_length=TZ_MAX)
    rrule: str | None = Field(default=None, max_length=_RULE_MAX)
    """PR 2's normalised rule text (already allow-listed)."""
    recurrence_until: datetime | None = dt_col()
    overrides: list[Any] = json_col(list)
    """``[{original_start, kind, starts_at, ends_at}]`` (UTC ISO strings)."""
    span_start: datetime = dt_required()
    span_end: datetime | None = dt_col()

    title: str = Field(max_length=SUBSCRIPTION_ITEM_TITLE_MAX)
    location: str | None = Field(default=None, max_length=SUBSCRIPTION_ITEM_LOCATION_MAX)
    url: str | None = Field(default=None, max_length=SUBSCRIPTION_ITEM_URL_MAX)
    cancelled: bool = flag()
    private_class: bool = flag()

    content_hash: str = Field(max_length=_HASH_LEN)
    seen_generation: int
    updated_at: datetime = dt_col(nullable=False)
