"""A category: a tenant-wide label with a name per content language."""

from __future__ import annotations

import uuid

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from sm_events.core.constants import SLUG_MAX
from sm_events.models._base import Base
from sm_events.models._cols import json_col, pk_uuid


class Category(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_category"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_events_category_tenant_slug"),)

    id: uuid.UUID = pk_uuid()
    slug: str = Field(max_length=SLUG_MAX)
    names: dict[str, str] = json_col(dict)
    """``{locale: name}``."""
    color: str | None = Field(default=None, max_length=7)
