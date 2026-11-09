"""A campaign: one email, its audience, its lifecycle and its counters.

The counters are denormalised totals the dispatcher and the tracking routes
bump, so the campaign list never aggregates ``newsletter_send``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import Index
from sqlmodel import Field

from sm_newsletter.core.constants import MAX_EMAIL_LEN, MAX_PAUSED_REASON, MAX_TYPE_KEY_LEN
from sm_newsletter.models._base import Base
from sm_newsletter.models._cols import STATUS_LEN, counter, dt_col, json_col


class Campaign(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "newsletter_campaign"
    __table_args__ = (
        Index("ix_newsletter_campaign_tenant_status", "tenant_id", "status"),
        # The dispatcher's oldest-first scan across tenants.
        Index("ix_newsletter_campaign_status_started", "status", "started_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=200)
    subject: str = Field(default="", max_length=300)
    preheader: str = Field(default="", max_length=300)
    from_name: str | None = Field(default=None, max_length=200)
    reply_to: str | None = Field(default=None, max_length=MAX_EMAIL_LEN)
    body: list[Any] = json_col(list)
    """The email's blocks."""
    list_type_key: str = Field(max_length=MAX_TYPE_KEY_LEN)
    """The records subscription list (a record type key) it goes to."""
    audience: str = Field(default="all", max_length=140)
    """``all`` or a segment of that list."""
    status: str = Field(default="draft", max_length=STATUS_LEN)
    revision: int = Field(default=1, sa_column_kwargs={"nullable": False, "server_default": "1"})
    """Bumped by every write; an editor's PATCH names the one it read."""
    paused_reason: str | None = Field(default=None, max_length=MAX_PAUSED_REASON)
    freeze_gen: int = Field(default=0, sa_column_kwargs={"nullable": False, "server_default": "0"})
    """Bumped by schedule, unschedule and cancel-from-scheduled; fences an
    interrupted freeze."""
    freeze_owner: str | None = Field(default=None, max_length=64)
    freeze_until: datetime | None = dt_col()
    """The freeze claim: one owner at a time, until this instant."""
    scheduled_at: datetime | None = dt_col()
    started_at: datetime | None = dt_col()
    finished_at: datetime | None = dt_col()

    recipient_count: int = counter()
    sent_count: int = counter()
    failed_count: int = counter()
    bounced_count: int = counter()
    suppressed_count: int = counter()
    open_unique_count: int = counter()
    open_total_count: int = counter()
    click_unique_count: int = counter()
    click_total_count: int = counter()
    unsubscribe_count: int = counter()
