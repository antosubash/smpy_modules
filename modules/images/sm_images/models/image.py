"""Images: one row per uploaded or imported picture."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from simple_module_db.mixins import AuditMixin, MultiTenantMixin, SoftDeleteMixin
from sqlalchemy import BigInteger, CheckConstraint, Index, SmallInteger, text
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import dt_col, fk_uuid, json_null, pk_uuid
from sm_images.models.enums import LocationSource

IMAGE_EXTERNAL_INDEX = "uq_images_image_external"
IMAGE_GALLERY_INDEX = "ix_images_image_gallery"
IMAGE_UNPROCESSED_INDEX = "ix_images_image_unprocessed"
IMAGE_COORDS_CHECK = "coords_paired"
IMAGE_EXTERNAL_CHECK = "external_sourced"
"""An external id without a source would never dedupe (NULL is distinct in a
unique index), so the pair is enforced together."""
_HAS_EXTERNAL_ID = text("external_id IS NOT NULL")
_UNPROCESSED = text("processed_generation < processing_generation")


class Image(Base, AuditMixin, SoftDeleteMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_image"
    __table_args__ = (
        CheckConstraint("(lat IS NULL) = (lng IS NULL)", name=IMAGE_COORDS_CHECK),
        CheckConstraint(
            "external_id IS NULL OR external_source IS NOT NULL", name=IMAGE_EXTERNAL_CHECK
        ),
        Index(
            IMAGE_EXTERNAL_INDEX,
            "collection_id",
            "external_source",
            "external_id",
            unique=True,
            sqlite_where=_HAS_EXTERNAL_ID,
            postgresql_where=_HAS_EXTERNAL_ID,
        ),
        Index(IMAGE_GALLERY_INDEX, "collection_id", "created_at", "id"),
        # What reconcile scans for a processing cycle that never concluded.
        Index(
            IMAGE_UNPROCESSED_INDEX,
            "tenant_id",
            "id",
            sqlite_where=_UNPROCESSED,
            postgresql_where=_UNPROCESSED,
        ),
    )
    __audit_exclude_fields__: ClassVar[set[str]] = {
        "processing_generation",
        "processed_generation",
        "purge_failed_at",
    }

    id: uuid.UUID = pk_uuid()
    collection_id: uuid.UUID = fk_uuid("images_collection.id")

    storage_key: str = Field(max_length=500)
    """The original. Immutable: nothing writes this after insert."""
    display_key: str | None = Field(default=None, max_length=500)
    """``None`` = the original is the display copy."""
    display_generation: int = Field(default=0, sa_column_kwargs={"nullable": False})
    """Fences display publication (``WHERE display_generation = :g - 1``)."""
    display_step: str | None = Field(default=None, max_length=100)
    """The step that wrote the current display copy, stamped at its fenced
    publication. A display copy is trusted as redacted only while this is the
    collection's enabled display mutator (``sm_images.access.redaction``): a crop is a
    display mutator too, and redacts nothing."""
    display_step_version: int | None = Field(default=None)
    processing_generation: int = Field(default=1, sa_column_kwargs={"nullable": False})
    """The processing cycle: bumped once by an accepted retry, force or re-run."""
    processed_generation: int = Field(default=0, sa_column_kwargs={"nullable": False})
    """The last cycle ``ImageProcessed`` was decided for; equal to
    ``processing_generation`` once every enabled step of that cycle is final.
    Conditional ``UPDATE`` on these two is what makes the event fire once."""
    purge_failed_at: datetime | None = dt_col()
    """When the janitor last failed to delete this (trashed) image's objects;
    such images go to the back of later purge passes (``sm_images.jobs.purge``)."""
    storage_hold_id: str | None = Field(default=None, max_length=64)
    storage_bytes: int = Field(default=0, sa_type=BigInteger, sa_column_kwargs={"nullable": False})
    """Sum of this image's objects (original, display copy, renditions), as held
    against the storage gauge (``sm_images.billing``)."""
    display_bytes: int = Field(default=0, sa_type=BigInteger, sa_column_kwargs={"nullable": False})
    """The display copy's size; ``0`` while the original is the display copy."""

    filename: str = Field(max_length=255)
    content_type: str = Field(max_length=100)
    size_bytes: int = Field(sa_type=BigInteger, sa_column_kwargs={"nullable": False})
    width: int | None = Field(default=None)
    height: int | None = Field(default=None)
    sha256: str | None = Field(default=None, max_length=64, index=True)

    lat: float | None = Field(default=None)
    lng: float | None = Field(default=None)
    altitude: float | None = Field(default=None)
    heading: float | None = Field(default=None)
    location_source: LocationSource | None = Field(
        default=None, sa_type=SmallInteger, sa_column_kwargs={"nullable": True}
    )
    """Precedence, compared in SQL: manual (3) > import (2) > exif (1)."""

    captured_at: datetime | None = dt_col()
    camera_make: str | None = Field(default=None, max_length=100)
    camera_model: str | None = Field(default=None, max_length=100)
    orientation: int | None = Field(default=None)

    external_source: str | None = Field(default=None, max_length=100)
    external_id: str | None = Field(default=None, max_length=255)
    properties: dict[str, Any] | None = json_null()

    group_id: uuid.UUID | None = fk_uuid("images_group.id", nullable=True)
    group_role: str | None = Field(default=None, max_length=50)
