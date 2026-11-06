"""A named, saved filter over one subscription list."""

from __future__ import annotations

from typing import Any

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from sm_newsletter.core.constants import MAX_TYPE_KEY_LEN
from sm_newsletter.models._base import Base
from sm_newsletter.models._cols import json_col


class Segment(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "newsletter_segment"
    __table_args__ = (
        UniqueConstraint("tenant_id", "list_type_key", "name", name="uq_newsletter_segment_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=200)
    list_type_key: str = Field(max_length=MAX_TYPE_KEY_LEN)
    filters: list[str] = json_col(list)
    rules: list[dict[str, Any]] = json_col(list, server_default="'[]'")
    """The editor's rows; ``filters`` stays the compiled terms."""
