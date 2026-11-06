"""Per-recipient delivery: one ``Send`` per subscriber per campaign, and the
ledger of every SMTP attempt made for it (or for a test send)."""

from __future__ import annotations

from datetime import datetime

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field

from sm_newsletter.core.constants import MAX_EMAIL_LEN, MAX_FIRST_NAME_LEN
from sm_newsletter.models._base import Base
from sm_newsletter.models._cols import STATUS_LEN, big_pk, counter, dt_col, fk


class Send(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "newsletter_send"
    __table_args__ = (
        # The no-duplicate guarantee: a subscriber gets a campaign at most once.
        UniqueConstraint(
            "tenant_id", "campaign_id", "record_uuid", name="uq_newsletter_send_campaign_record"
        ),
        Index("ix_newsletter_send_campaign_status", "campaign_id", "status", "id"),
        Index("ix_newsletter_send_record", "tenant_id", "record_uuid", "id"),
    )

    id: int | None = big_pk()
    campaign_id: int = fk("newsletter_campaign.id", ondelete="CASCADE")
    record_uuid: str = Field(max_length=32)
    email: str = Field(max_length=MAX_EMAIL_LEN)
    first_name: str | None = Field(default=None, max_length=MAX_FIRST_NAME_LEN)
    """Stored at freeze for the worker's ``{{first_name}}`` merge."""
    status: str = Field(default="queued", max_length=STATUS_LEN)
    attempts: int = counter()
    lease_until: datetime | None = dt_col()
    retry_at: datetime | None = dt_col()
    """A queued row is not due before it."""
    freeze_gen: int = Field(default=0, sa_column_kwargs={"nullable": False, "server_default": "0"})
    """The campaign's freeze generation this row was written under."""
    sent_at: datetime | None = dt_col()
    opened_at: datetime | None = dt_col()
    first_clicked_at: datetime | None = dt_col()
    open_count: int = counter()
    last_error: str | None = Field(default=None, max_length=1000)
    error_kind: str | None = Field(default=None, max_length=STATUS_LEN)


class SendAttempt(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    """One row per recipient per SMTP attempt, a campaign's or a test send's;
    ``outcome`` starts ``pending``."""

    __tablename__ = "newsletter_send_attempt"
    __table_args__ = (Index("ix_newsletter_send_attempt_at", "attempted_at"),)

    id: int | None = big_pk()
    send_id: int | None = fk("newsletter_send.id", ondelete="SET NULL", nullable=True, big=True)
    """``None`` for a test send."""
    campaign_id: int | None = fk("newsletter_campaign.id", ondelete="SET NULL", nullable=True)
    kind: str = Field(max_length=8)
    recipient: str = Field(max_length=MAX_EMAIL_LEN)
    attempted_at: datetime = dt_col(nullable=False)
    outcome: str = Field(default="pending", max_length=16)
    smtp_code: int | None = Field(default=None)
    detail: str | None = Field(default=None, max_length=500)
