"""One feature (URL mode) or one zip member of an import job."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import dt_col, enum_col, fk_uuid, json_null
from sm_images.models.enums import ItemStatus


class ImportItem(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_import_item"
    __table_args__ = (
        UniqueConstraint("job_id", "feature_index", name="uq_images_import_item_job_feature"),
        Index("ix_images_import_item_job_status", "job_id", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    job_id: uuid.UUID = fk_uuid("images_import_job.id", ondelete="CASCADE")
    feature_index: int = Field(sa_column_kwargs={"nullable": False})
    url: str | None = Field(default=None, max_length=2000)
    external_id: str | None = Field(default=None, max_length=255)
    status: ItemStatus = enum_col(ItemStatus, "item_status", ItemStatus.PENDING)
    attempts: int = Field(default=0, sa_column_kwargs={"nullable": False})
    last_error: str | None = Field(default=None, max_length=2000)
    lat: float | None = Field(default=None)
    lng: float | None = Field(default=None)
    captured_at: datetime | None = dt_col()
    group_key: str | None = Field(default=None, max_length=200)
    group_role: str | None = Field(default=None, max_length=50)
    properties: dict[str, Any] | None = json_null()
    image_id: uuid.UUID | None = fk_uuid("images_image.id", nullable=True, ondelete="SET NULL")
