"""Image groups (the portal's "bags"): a point plus its directional shots."""

from __future__ import annotations

import uuid

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import fk_uuid, pk_uuid


class Group(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_group"
    __table_args__ = (
        UniqueConstraint("collection_id", "key", name="uq_images_group_collection_key"),
    )

    id: uuid.UUID = pk_uuid()
    collection_id: uuid.UUID = fk_uuid("images_collection.id")
    key: str = Field(max_length=200)
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
