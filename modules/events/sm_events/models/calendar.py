"""A calendar: the unit of access. Events live in one."""

from __future__ import annotations

import uuid
from typing import Any

from simple_module_db.mixins import AuditMixin, MultiTenantMixin, SoftDeleteMixin
from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlmodel import Field

from sm_events.core.constants import DEFAULT_COLOR, SLUG_MAX, TZ_MAX
from sm_events.models._base import Base
from sm_events.models._cols import json_col, pk_uuid
from sm_events.models.enums import Visibility

CALENDAR_SLUG_CONSTRAINT = "uq_events_calendar_tenant_slug"


class Calendar(Base, AuditMixin, SoftDeleteMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_calendar"
    __table_args__ = (
        # Slugs stay unique across the trash, so a restore never collides.
        UniqueConstraint("tenant_id", "slug", name=CALENDAR_SLUG_CONSTRAINT),
        Index("ix_events_calendar_tenant_visibility", "tenant_id", "visibility"),
    )

    id: uuid.UUID = pk_uuid()
    slug: str = Field(max_length=SLUG_MAX)
    name: str = Field(max_length=200)
    color: str = Field(default=DEFAULT_COLOR, max_length=7)
    description: str | None = Field(default=None, max_length=2000)
    visibility: str = Field(default=Visibility.PRIVATE.value, max_length=16)
    owner_id: str = Field(max_length=64, index=True)
    default_timezone: str = Field(default="UTC", max_length=TZ_MAX)
    sources: list[Any] = json_col(list)
    """Plugin source ids only; the built-in ``events`` source is always on and
    never listed."""
    default_reminder_minutes: list[int] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    """Lead times (minutes, each in ``REMINDER_LEADS``) that "Remind me" preselects here;
    ``NULL`` means the install-wide setting. Nobody is followed automatically."""
