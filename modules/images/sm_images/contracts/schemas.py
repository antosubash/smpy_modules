"""Wire shapes of the contract reads. Output only: no input bounds here, so a
stored row that predates a bound never fails to serialise."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlmodel import SQLModel

__all__ = ["CollectionPageRead", "CollectionRead", "ImageRead", "collection_fields"]


def collection_fields(row: Any) -> dict[str, Any]:
    corners = (row.bbox_minx, row.bbox_miny, row.bbox_maxx, row.bbox_maxy)
    return {
        "id": row.id,
        "slug": row.slug,
        "name": row.name,
        "description": row.description,
        "owner_id": row.owner_id,
        "visibility": row.visibility.value,
        "image_count": row.image_count,
        "located_count": row.located_count,
        "bbox": None if None in corners else list(corners),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class CollectionRead(SQLModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    owner_id: str
    visibility: str
    image_count: int
    located_count: int
    bbox: list[float] | None
    """``[minx, miny, maxx, maxy]`` of the located images, or ``None``."""
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_row(cls, row: Any) -> CollectionRead:
        return cls(**collection_fields(row))


class CollectionPageRead(SQLModel):
    items: list[CollectionRead]
    next_cursor: str | None
    total: int | None
    """Counted on the first page only; carry it from there."""


class ImageRead(BaseModel):
    """Metadata of one image, for a pipeline step: no ORM object, no storage
    keys (a step reads bytes through ``StepContext``). Frozen."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    collection_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    sha256: str | None = None
    lat: float | None = None
    lng: float | None = None
    altitude: float | None = None
    heading: float | None = None
    location_source: int | None = None
    captured_at: datetime | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    orientation: int | None = None
    external_source: str | None = None
    external_id: str | None = None
    properties: dict[str, Any] | None = None
    group_id: uuid.UUID | None = None
    group_role: str | None = None
    display_generation: int = 0

    @classmethod
    def from_row(cls, row: Any) -> ImageRead:
        data = {n: getattr(row, n) for n in cls.model_fields if n != "location_source"}
        source = row.location_source
        return cls(**data, location_source=None if source is None else int(source))
