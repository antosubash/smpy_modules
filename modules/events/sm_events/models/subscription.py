"""An external ICS subscription: a calendar's link to a remote feed, and its fetch state.

The address is a credential (private calendar links carry a bearer token in the path or the
query), so it is stored **only** sealed (``url_enc``, ``enc:v2:`` from this module's copy of the
stored-secret crypto) beside the masked ``url_display`` the API and the screen show. A deleted
row keeps neither: ``url_enc`` is emptied when it is deleted.

The lease columns are the beat's claim (compare-and-set, fenced when the result is stored); the
conditional-request validators and counters belong to the fetch and are never shown.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from simple_module_db.mixins import MultiTenantMixin, SoftDeleteMixin
from sqlalchemy import Column, Index, Text
from sqlmodel import Field

from sm_events.core.constants import (
    SUBSCRIPTION_CODE_MAX,
    SUBSCRIPTION_ETAG_MAX,
    SUBSCRIPTION_LABEL_MAX,
    SUBSCRIPTION_LAST_MODIFIED_MAX,
    SUBSCRIPTION_LEASE_OWNER_MAX,
    SUBSCRIPTION_STATUS_MAX,
    URL_DISPLAY_MAX,
)
from sm_events.models._base import Base
from sm_events.models._cols import counter, dt_col, fk_uuid, flag, json_col, pk_uuid


class Subscription(Base, SoftDeleteMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_subscription"
    __table_args__ = (
        # The beat's scan: due rows across every tenant, by status then time.
        Index("ix_events_subscription_due", "status", "next_fetch_at"),
        Index("ix_events_subscription_calendar", "tenant_id", "calendar_id"),
    )

    id: uuid.UUID = pk_uuid()
    calendar_id: uuid.UUID = fk_uuid("events_calendar.id", ondelete="CASCADE")
    created_by: str = Field(max_length=64)

    url_enc: str = Field(sa_column=Column(Text, nullable=False))
    """``enc:v2:`` ciphertext of the address; ``""`` once the row is deleted."""
    url_display: str = Field(max_length=URL_DISPLAY_MAX)
    """``scheme://host[:port]/…``: everything of the address the console ever shows."""

    label: str = Field(max_length=SUBSCRIPTION_LABEL_MAX)
    color: str | None = Field(default=None, max_length=7)
    """``#rrggbb``; ``NULL`` means the calendar's own colour."""
    refresh_minutes: int | None = None
    """The subscriber's own interval; ``NULL`` means the install-wide setting. Clamped on read."""
    public: bool = flag()
    """Whether anonymous visitors may see its items (only on a public calendar)."""

    status: str = Field(default="pending", max_length=SUBSCRIPTION_STATUS_MAX)
    """One of ``constants.SUBSCRIPTION_STATUSES``."""
    error_code: str | None = Field(default=None, max_length=SUBSCRIPTION_CODE_MAX)
    """One of ``constants.SUBSCRIPTION_FAILURE_CODES``; kept as the reason once disabled."""
    last_http_status: int | None = None
    """The remote's status number (never its reason text) after a ``http_status`` failure."""

    etag: str | None = Field(default=None, max_length=SUBSCRIPTION_ETAG_MAX)
    last_modified: str | None = Field(default=None, max_length=SUBSCRIPTION_LAST_MODIFIED_MAX)
    """The remote's validators, sent back as ``If-None-Match`` / ``If-Modified-Since``. Never
    returned by the API."""

    last_fetched_at: datetime | None = dt_col()
    last_ok_at: datetime | None = dt_col()
    next_fetch_at: datetime | None = dt_col()

    consecutive_failures: int = counter()
    generation: int = counter()
    """Incremented once per full successful 200; items of an older generation are pruned."""
    item_count: int = counter()
    last_counts: dict[str, Any] = json_col(dict)
    """``{stored, skipped, reasons: {code: n}}`` of the last stored fetch."""

    lease_owner: str | None = Field(default=None, max_length=SUBSCRIPTION_LEASE_OWNER_MAX)
    lease_until: datetime | None = dt_col()

    created_at: datetime = dt_col(nullable=False)
    updated_at: datetime = dt_col(nullable=False)
