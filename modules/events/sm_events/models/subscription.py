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
    URL_HOST_MAX,
)
from sm_events.models._base import Base
from sm_events.models._cols import counter, dt_col, fk_uuid, flag, json_col, pk_uuid


class Subscription(Base, SoftDeleteMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_subscription"
    __table_args__ = (
        # The beat's scan: due rows across every tenant, by status then time.
        Index("ix_events_subscription_due", "status", "next_fetch_at"),
        Index("ix_events_subscription_calendar", "tenant_id", "calendar_id"),
        # The per-host floor looks a tenant's rows up by host.
        Index("ix_events_subscription_host", "tenant_id", "url_host"),
    )

    id: uuid.UUID = pk_uuid()
    calendar_id: uuid.UUID = fk_uuid("events_calendar.id", ondelete="CASCADE")
    created_by: str = Field(max_length=64)

    url_enc: str = Field(sa_column=Column(Text, nullable=False))
    """``enc:v2:`` ciphertext of the address; ``""`` once the row is deleted."""
    url_host: str = Field(default="", max_length=URL_HOST_MAX)
    """The address's host (already in ``url_display``): what the per-host floor groups by. Kept
    when the row is deleted, so the floor survives it."""
    url_display: str = Field(max_length=URL_DISPLAY_MAX)
    """``scheme://host[:port]/…``: everything of the address the console ever shows."""

    label: str = Field(max_length=SUBSCRIPTION_LABEL_MAX)
    color: str | None = Field(default=None, max_length=7)
    """``#rrggbb``; ``NULL`` means the calendar's own colour."""
    refresh_minutes: int | None = None
    """The subscriber's own interval; ``NULL`` means the install-wide setting. Clamped on read."""
    public: bool = flag()
    """Whether anonymous visitors may see its items (only on a public calendar)."""

    may_use_private: bool = flag()
    """(The API and the UI say ``may_use_internal_addresses``; the column keeps its first name.)
    Whether the address may be an internal one: set at save from the saver's ``events.manage``
    (never from a request body) and re-evaluated when the address changes. The intranet setting
    must also be on, at every fetch and every redirect hop. Stays when the saver later loses the
    permission, until the address is edited."""

    policy_generation: int = counter()
    """Bumped whenever ``public``, ``may_use_private`` or the address changes. A fetch records the
    value it started under and its result is discarded if the row has moved on."""
    items_generation: int = counter()
    """The ``policy_generation`` the stored items were fetched under. Every read returns items
    only while it equals ``policy_generation``."""

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
    last_attempt_at: datetime | None = dt_col()
    """When an attempt was last claimed (even one whose result was discarded): the host floor."""
    slow_count: int = counter()
    """Slow fetches in a row (``constants.SUBSCRIPTION_SLOW_SECONDS``); one fast success resets."""

    consecutive_failures: int = counter()
    generation: int = counter()
    """Incremented once per full successful 200; items of an older generation are pruned. Not the
    policy generation (``policy_generation`` / ``items_generation``, which say which address and
    policy the stored items belong to), nor an item's ``seen_generation`` (the value of this
    counter when the fetch last saw it)."""
    item_count: int = counter()
    last_counts: dict[str, Any] = json_col(dict)
    """``{stored, skipped, reasons: {code: n}}`` of the last stored fetch."""

    lease_owner: str | None = Field(default=None, max_length=SUBSCRIPTION_LEASE_OWNER_MAX)
    lease_until: datetime | None = dt_col()

    created_at: datetime = dt_col(nullable=False)
    updated_at: datetime = dt_col(nullable=False)
