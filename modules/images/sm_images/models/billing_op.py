"""The durable outbox of storage-gauge settlements (``sm_images.billing_ops``).

An ``ingest`` op takes a new image's first hold (a swap from no hold); a
``swap`` op moves one image's hold to a new quantity through billing's
atomic ``swap`` (the new hold committed and the old one released in one
billing transaction); its ``idempotency_key`` makes a retry return the same
hold. A ``release`` op returns a purged image's hold. An image's ``swap`` ops
run one at a time, oldest first, and an op that is running is claimed
(``claim_token``) so only its claimant may finish it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import BigInteger, Index, UniqueConstraint, Uuid
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import dt_col

OP_INGEST = "ingest"
OP_SWAP = "swap"
OP_RELEASE = "release"
OP_EXPIRED = "op_expired"
"""``last_error`` of an op finished at its deadline, without billing."""
BILLING_OP_MAX_AGE = timedelta(days=7)
"""An op's deadline (``not_after``) is its creation plus this. Billing refuses
any call after it (``Expired``), and keeps a key's outcome 30 days after it
settles, so every call that can still mutate is answered by its key."""
NO_HOLD = "-"
"""``old_hold_id`` of a swap from no hold (``NULL`` is: not fixed yet)."""


class BillingOp(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_billing_op"
    __table_args__ = (Index("ix_images_billing_op_due", "tenant_id", "done_at", "id"),)

    id: int | None = Field(default=None, primary_key=True)
    image_id: uuid.UUID | None = Field(default=None, sa_type=Uuid, nullable=True)
    """No foreign key: an op outlives a purged image row."""
    op: str = Field(max_length=16)
    hold_id: str | None = Field(default=None, max_length=64)
    """A ``release``'s hold; a ``swap``'s new hold, recorded when it is installed."""
    old_hold_id: str | None = Field(default=None, max_length=64)
    """The hold a ``swap`` replaces, fixed before billing first hears of it (every
    retry names the same one: billing refuses a replay naming another);
    :data:`NO_HOLD` for none."""
    quantity: int = Field(default=0, sa_type=BigInteger, sa_column_kwargs={"nullable": False})
    idempotency_key: str | None = Field(default=None, max_length=128)
    attempts: int = Field(default=0, sa_column_kwargs={"nullable": False})
    next_attempt_at: datetime | None = dt_col()
    done_at: datetime | None = dt_col()
    last_error: str | None = Field(default=None, max_length=500)
    claim_token: str | None = Field(default=None, max_length=64)
    """The settler (or executor, or ingest) running this op; only it may finish it."""
    claim_expires_at: datetime | None = dt_col()
    repaired_at: datetime | None = dt_col()
    """When the repair (``sm_images.billing_repair``) examined this done op."""
    not_after: datetime | None = dt_col()
    """The op's deadline, passed to billing with every call it makes."""
    """When the repair (``sm_images.billing_repair``) examined this done op."""


class BillingRepairCursor(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    """How far the repair's scan of a tenant's done ops has got (op id)."""

    __tablename__ = "images_billing_cursor"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_images_billing_cursor_tenant"),)

    id: int | None = Field(default=None, primary_key=True)
    last_op_id: int = Field(default=0, sa_column_kwargs={"nullable": False})
