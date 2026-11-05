"""Tracked links: each campaign's distinct URLs, and each recipient's clicks on one."""

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
    """One row per recipient per link: the first click's time and how many (T8)."""

    __tablename__ = "newsletter_click"
    __table_args__ = (
        UniqueConstraint("tenant_id", "send_id", "link_id", name="uq_newsletter_click_send_link"),
    )

    id: int | None = big_pk()
    send_id: int = fk("newsletter_send.id", ondelete="CASCADE", big=True)
    link_id: int = fk("newsletter_link.id", ondelete="CASCADE")
    clicked_at: datetime = dt_col(nullable=False)  # the first click
    click_count: int = Field(default=1, sa_column_kwargs={"nullable": False, "server_default": "1"})
