"""Wire shapes of the contract reads. Output only: no input bounds here, so a
stored row that predates a bound never fails to serialise."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import SQLModel

__all__ = ["CollectionPageRead", "CollectionRead", "collection_fields"]


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
