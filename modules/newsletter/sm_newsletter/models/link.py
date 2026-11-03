"""Tracked links: each campaign's distinct URLs, and every click on one."""

from __future__ import annotations

from datetime import datetime

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from sm_newsletter.models._base import Base
from sm_newsletter.models._cols import big_pk, dt_col, fk


class Link(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "newsletter_link"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "campaign_id", "position", name="uq_newsletter_link_position"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    campaign_id: int = fk("newsletter_campaign.id", ondelete="CASCADE")
    position: int
    url: str = Field(max_length=2048)


class Click(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "newsletter_click"

    id: int | None = big_pk()
    send_id: int = fk("newsletter_send.id", ondelete="CASCADE", big=True)
    link_id: int = fk("newsletter_link.id", ondelete="CASCADE")
    clicked_at: datetime = dt_col(nullable=False)
