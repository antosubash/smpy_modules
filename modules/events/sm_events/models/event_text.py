"""An event's words in one language."""

from __future__ import annotations

import uuid

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import Column, Text, UniqueConstraint
from sqlmodel import Field

from sm_events.core.constants import LOCALE_MAX, TEXT_SLUG_MAX
from sm_events.models._base import Base
from sm_events.models._cols import big_pk, fk_uuid, flag


class EventText(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_event_text"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", "locale", name="uq_events_event_text_locale"),
        UniqueConstraint("tenant_id", "locale", "slug", name="uq_events_event_text_slug"),
    )

    id: int | None = big_pk()
    event_id: uuid.UUID = fk_uuid("events_event.id", ondelete="CASCADE")
    locale: str = Field(max_length=LOCALE_MAX)
    slug: str = Field(max_length=TEXT_SLUG_MAX)
    title: str = Field(max_length=300)
    summary: str | None = Field(default=None, max_length=1000)
    description: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    """Allow-listed HTML, written only by PR 2's sanitiser."""
    seo_title: str | None = Field(default=None, max_length=300)
    seo_description: str | None = Field(default=None, max_length=500)
    noindex: bool = flag()
