"""The durable outbox of storage-gauge settlements (``sm_images.billing_ops``).

A row is written in the same transaction as the state change it settles - an
image inserted, a display copy or rendition set published, an image purged -
and stays until billing has confirmed it. ``after_id`` orders an image's
settlements: a ``release`` of its old hold waits for the ``commit`` (or the
``rehold`` that replaced it) of its new one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import BigInteger, Index, Uuid
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import dt_col

OP_COMMIT = "commit"
OP_RELEASE = "release"
OP_REHOLD = "rehold"


class BillingOp(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_billing_op"
    __table_args__ = (Index("ix_images_billing_op_due", "tenant_id", "done_at", "id"),)

    id: int | None = Field(default=None, primary_key=True)
    image_id: uuid.UUID | None = Field(default=None, sa_type=Uuid, nullable=True)
    """No foreign key: a purge's release outlives the image row."""
    op: str = Field(max_length=16)
    hold_id: str | None = Field(default=None, max_length=64)
    quantity: int = Field(default=0, sa_type=BigInteger, sa_column_kwargs={"nullable": False})
    idempotency_key: str | None = Field(default=None, max_length=128)
    after_id: int | None = Field(default=None)
    """Runs only once this op is done."""
    attempts: int = Field(default=0, sa_column_kwargs={"nullable": False})
    next_attempt_at: datetime | None = dt_col()
    done_at: datetime | None = dt_col()
    last_error: str | None = Field(default=None, max_length=500)
    claim_token: str | None = Field(default=None, max_length=64)
    """The settler executing this op; only it may move or finish it."""
    claim_expires_at: datetime | None = dt_col()
    replacement_hold_id: str | None = Field(default=None, max_length=64)
    """A ``rehold``'s replacement, persisted before it is committed."""
    generation: int = Field(default=0, sa_column_kwargs={"nullable": False})
    """A ``rehold``'s attempt: its replacement is keyed ``rehold-{id}-{generation}``."""
