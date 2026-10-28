"""Collections: the unit of access, pipeline configuration and map."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from simple_module_db.mixins import AuditMixin, MultiTenantMixin, SoftDeleteMixin
from sqlalchemy import Index
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import dt_col, enum_col, json_col, pk_uuid
from sm_images.models.enums import Visibility

COLLECTION_SLUG_INDEX = "uq_images_collection_tenant_slug"


class Collection(Base, AuditMixin, SoftDeleteMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_collection"
    __table_args__ = (Index(COLLECTION_SLUG_INDEX, "tenant_id", "slug", unique=True),)
    __audit_exclude_fields__: ClassVar[set[str]] = {"purge_failed_at"}

    id: uuid.UUID = pk_uuid()
    slug: str = Field(max_length=100)
    name: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    owner_id: str = Field(max_length=64, index=True)
    visibility: Visibility = enum_col(Visibility, "visibility", Visibility.PRIVATE)

    pipeline_config: dict[str, Any] = json_col(dict)
    """Enabled steps plus per-step params (spec §3)."""
    preset_id: str | None = Field(default=None, max_length=100)
    group_roles: list[str] = json_col(list)
    """Ordered role list, e.g. ``["point", "north", "east", "south", "west"]``."""

    image_count: int = Field(default=0, sa_column_kwargs={"nullable": False})
    located_count: int = Field(default=0, sa_column_kwargs={"nullable": False})
    bbox_minx: float | None = Field(default=None)
    bbox_miny: float | None = Field(default=None)
    bbox_maxx: float | None = Field(default=None)
    bbox_maxy: float | None = Field(default=None)
    map_built_at: datetime | None = dt_col()
    map_image_count: int = Field(default=0, sa_column_kwargs={"nullable": False})
    """Located-image count the current map was built from; a drift from
    ``located_count`` is what tells the scheduler the map is stale."""
    protect_originals: bool = Field(default=False, sa_column_kwargs={"nullable": False})
    """Set when a saved pipeline enabled a step registered as a display mutator.
    Serving reads this, not the live registry, so uninstalling the plugin never
    unprotects an original; only an owner's save of a config with no mutator,
    every step of it installed, clears it (``pipeline.config.protect_originals``)."""
    purge_failed_at: datetime | None = dt_col()
    """When the janitor last failed to purge this (trashed) collection, or one
    of its images; it then goes to the back of later passes (``sm_images.purge``)."""
