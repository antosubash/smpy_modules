"""A private feed link: who it belongs to, and the digest that finds it.

Only the SHA-256 of the token is stored (never the token, never a hint of it), so a leaked
database cannot be replayed against the feed route. What the link shows is decided per request
from its owner's rights, never from anything kept here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field

from sm_events.core.constants import (
    LOCALE_MAX,
    TOKEN_HASH_LENGTH,
    TOKEN_LABEL_MAX,
    TOKEN_USER_MAX,
)
from sm_events.models._base import Base
from sm_events.models._cols import dt_col, fk_uuid, pk_uuid

TOKEN_HASH_CONSTRAINT = "uq_events_feed_token_hash"  # noqa: S105 - a constraint name


class FeedToken(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_feed_token"
    __table_args__ = (
        # Unique across every tenant: the route finds a row by hash before it knows a tenant.
        UniqueConstraint("token_hash", name=TOKEN_HASH_CONSTRAINT),
        Index("ix_events_feed_token_owner", "tenant_id", "calendar_id", "user_id"),
    )

    id: uuid.UUID = pk_uuid()
    calendar_id: uuid.UUID = fk_uuid("events_calendar.id", ondelete="CASCADE")
    user_id: str = Field(max_length=TOKEN_USER_MAX)
    token_hash: str = Field(max_length=TOKEN_HASH_LENGTH)
    label: str = Field(max_length=TOKEN_LABEL_MAX)
    locale: str = Field(max_length=LOCALE_MAX)
    created_at: datetime = dt_col(nullable=False)
    last_used_at: datetime | None = dt_col()
    revoked_at: datetime | None = dt_col()
    """Set on revocation; the janitor deletes the row ``FEED_REVOKED_KEPT_DAYS`` later."""
