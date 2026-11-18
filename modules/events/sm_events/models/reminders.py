"""Reminders (PR 8): who follows an event, and what has been sent.

``EventFollow`` is **personal data of one user**: every row carries the tenant and the user, and
nothing reads it across users except the reminder beat (which sends to each follower alone).
It stores ids and the language the user was using, never a snapshot of their rights or of the
event: whether someone may still be reminded is decided from current state when a reminder is
due.

``ReminderSent`` is the at-most-once ledger. A row is inserted (the *claim*) and committed
before any mail goes out; its unique key is what makes two concurrent ticks send one mail.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field

from sm_events.core.constants import (
    LOCALE_MAX,
    OCCURRENCE_KEY_MAX,
    REMINDER_CODE_MAX,
    REMINDER_USER_MAX,
)
from sm_events.models._base import Base
from sm_events.models._cols import big_pk, dt_col, dt_required, fk_uuid, pk_uuid

FOLLOW_CONSTRAINT = "uq_events_follow"
LEDGER_CONSTRAINT = "uq_events_reminder_sent"


class EventFollow(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    """One user's wish to be reminded ``lead_minutes`` before every occurrence of an event.
    One row per lead; no soft delete (unfollowing deletes the row)."""

    __tablename__ = "events_follow"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "event_id", "lead_minutes", name=FOLLOW_CONSTRAINT
        ),
        Index("ix_events_follow_event", "tenant_id", "event_id"),
        Index("ix_events_follow_user", "tenant_id", "user_id"),
    )

    id: uuid.UUID = pk_uuid()
    user_id: str = Field(max_length=REMINDER_USER_MAX)
    event_id: uuid.UUID = fk_uuid("events_event.id", ondelete="CASCADE")
    lead_minutes: int
    locale: str = Field(max_length=LOCALE_MAX)
    """The console language when the follow was written; the mail is rendered in it."""
    created_at: datetime = dt_col(nullable=False)


class ReminderSent(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    """The ledger: one row per ``(occurrence, start, recipient, lead)``, ``sending`` from the
    claim, ``sent`` or ``failed`` after. A failed or unfinished row is final; nothing retries."""

    __tablename__ = "events_reminder_sent"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "occurrence_key",
            "starts_at",
            "recipient_id",
            "lead_minutes",
            name=LEDGER_CONSTRAINT,
        ),
        Index("ix_events_reminder_sent_claimed", "tenant_id", "claimed_at"),
    )

    id: int | None = big_pk()
    event_id: uuid.UUID = fk_uuid("events_event.id", ondelete="CASCADE")
    occurrence_key: str = Field(max_length=OCCURRENCE_KEY_MAX)
    starts_at: datetime = dt_required()
    """The start this reminder announced (UTC); *which* occurrence is ``occurrence_key``."""
    recipient_id: str = Field(max_length=REMINDER_USER_MAX)
    lead_minutes: int
    state: str = Field(max_length=16)
    code: str | None = Field(default=None, max_length=REMINDER_CODE_MAX)
    claimed_at: datetime = dt_col(nullable=False)
    sent_at: datetime | None = dt_col()
