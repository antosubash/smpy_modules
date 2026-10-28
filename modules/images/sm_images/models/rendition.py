"""Renditions: sized JPEGs generated from the display copy."""

from __future__ import annotations

import uuid

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import fk_uuid


class Rendition(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_rendition"
    __table_args__ = (UniqueConstraint("image_id", "size", name="uq_images_rendition_image_size"),)

    id: int | None = Field(default=None, primary_key=True)
    image_id: uuid.UUID = fk_uuid("images_image.id", ondelete="CASCADE")
    size: str = Field(max_length=50)
    storage_key: str = Field(max_length=500)
    width: int = Field(sa_column_kwargs={"nullable": False})
    height: int = Field(sa_column_kwargs={"nullable": False})
