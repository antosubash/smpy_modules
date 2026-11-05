"""Addresses the module must not mail, keyed by a hash of the address.

Lookups are tenant-wide (``ix_newsletter_suppression_lookup``): a suppressed
address gets nothing from any list. ``list_type_key`` is provenance only, for
``unsubscribed`` rows (one per list the address left), and ``""`` for every
other reason; it is in the unique key so a confirmation on one list clears
that list's opt-out and leaves another's standing.
"""

from __future__ import annotations

from datetime import datetime

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field

from sm_newsletter.core.constants import MAX_TYPE_KEY_LEN
from sm_newsletter.models._base import Base
from sm_newsletter.models._cols import STATUS_LEN, big_pk, dt_col


class Suppression(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "newsletter_suppression"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "email_hash", "reason", "list_type_key", name="uq_newsletter_suppression"
        ),
        Index("ix_newsletter_suppression_lookup", "tenant_id", "email_hash"),
        Index("ix_newsletter_suppression_reason_at", "tenant_id", "reason", "created_at"),
    )

    id: int | None = big_pk()
    email_hash: str = Field(max_length=64)
    reason: str = Field(max_length=STATUS_LEN)
    list_type_key: str = Field(default="", max_length=MAX_TYPE_KEY_LEN)
    source: str = Field(max_length=STATUS_LEN)
    created_at: datetime = dt_col(nullable=False)
    """Refreshed by a repeat opt-out or bounce; compared with a confirmation's
    time, so a row older than the confirmation is the one it clears."""


class SuppressionLift(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    """An audit row for a suppression an admin lifted."""

    __tablename__ = "newsletter_suppression_lift"
    __table_args__ = (Index("ix_newsletter_suppression_lift_at", "tenant_id", "lifted_at"),)

    id: int | None = big_pk()
    email_hash: str = Field(max_length=64)
    reason: str = Field(max_length=STATUS_LEN)
    list_type_key: str = Field(default="", max_length=MAX_TYPE_KEY_LEN)
    source: str = Field(max_length=STATUS_LEN)
    suppressed_at: datetime = dt_col(nullable=False)
    lifted_at: datetime = dt_col(nullable=False)
    lifted_by: str | None = Field(default=None, max_length=64)
    note: str = Field(default="", max_length=500)
