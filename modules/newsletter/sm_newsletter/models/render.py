"""The rendered email of a scheduled campaign, one row per campaign.

It is stored because the worker never builds the app (ruling S1): the render
needs branding, the sender and the public base URL, which only the web process
resolves. Scheduling renders once, in the request, and writes this row in the
same transaction as ``draft -> scheduled``; the dispatcher only personalises it
(merge tags are left in place). Unscheduling deletes it, so scheduling again
renders afresh.
"""

from __future__ import annotations

from datetime import datetime

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import Column, ForeignKey, Integer, Text
from sqlmodel import Field

from sm_newsletter.core.constants import MAX_EMAIL_LEN
from sm_newsletter.models._base import Base
from sm_newsletter.models._cols import dt_col, json_col


class CampaignRender(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "newsletter_campaign_render"

    campaign_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("newsletter_campaign.id", ondelete="CASCADE"), primary_key=True
        ),
    )
    subject: str = Field(max_length=300)
    """Merge tags still in place."""
    html: str = Field(sa_column=Column(Text, nullable=False))
    text: str = Field(sa_column=Column(Text, nullable=False))
    sender: str = Field(max_length=600)
    """The formatted ``From``: ``Name <address>``."""
    reply_to: str | None = Field(default=None, max_length=MAX_EMAIL_LEN)
    public_base: str = Field(max_length=2048)
    """No trailing slash; the unsubscribe link is built on it."""
    content_base: str = Field(
        default="", max_length=2048, sa_column_kwargs={"nullable": False, "server_default": ""}
    )
    """No trailing slash; the campaign tenant's origin its content links were
    built on. Checked with ``public_base`` before SMTP delivery (an empty one
    counts as not ``https://``)."""
    locale: str = Field(max_length=16)
    rendered_at: datetime = dt_col(nullable=False)
    audience_filters: list[str] = json_col(list, server_default="'[]'")
    """The compiled segment terms the audience was resolved with at scheduling."""
