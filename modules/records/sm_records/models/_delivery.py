"""Who a website submission's notification has reached (#101).

One row per ``(tenant, record, attempt, recipient)``, unique, so claiming a
recipient for an attempt is an ``INSERT`` the database arbitrates: two outbox
workers running the same attempt cannot both send. ``sent_at`` is set once the
send went through, and a row with it is never sent again. ``claimed_at`` is the
lease of a claim not yet sent: a worker that crashed mid-send leaves it, and
it is taken over once older than the lease
(:mod:`sm_records.public_submissions.delivery`).

Internal bookkeeping: no API reads it, and a record purge leaves its rows
behind on purpose — a delete must not re-arm a notification. They carry no
field values, only the recipient addresses the type was configured with.
"""

from __future__ import annotations

from datetime import datetime

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field

from sm_records.models._base import GLOBAL_PREFIX, Base

__all__ = ["DELIVERY_TABLE", "DELIVERY_UNIQUE", "SubmissionDelivery"]

DELIVERY_TABLE = f"{GLOBAL_PREFIX}submission_delivery"
DELIVERY_UNIQUE = "uq_records_submission_delivery_claim"


class SubmissionDelivery(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = DELIVERY_TABLE
    __table_args__ = (
        UniqueConstraint("tenant_id", "record_uuid", "attempt", "recipient", name=DELIVERY_UNIQUE),
    )

    id: int | None = Field(default=None, primary_key=True)
    record_uuid: str = Field(max_length=32)
    attempt: str = Field(max_length=64)
    """``NotificationDue.attempt``: one per queued notification, so a *Resend*
    is a new attempt that reaches everyone again."""
    recipient: str = Field(max_length=320)
    claimed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    claim_token: str | None = Field(default=None, max_length=32)
    """Who holds the claim: release and "sent" are conditional on it."""
    sent_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
