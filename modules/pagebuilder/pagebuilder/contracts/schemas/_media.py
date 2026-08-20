"""Media assets, their metadata, and where they are used."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

PuckData = dict[str, Any]


class MediaAssetVariant(BaseModel):
    """One server-generated derivative of an uploaded image.

    Width is the canonical key for ``srcset`` so it's required; height is
    optional because some derivatives (e.g. a same-size webp transcode of
    a non-decodable input) may not carry it back.
    """

    filename: str
    url: str
    content_type: str
    width: int
    height: int | None = None
    size_bytes: int


class MediaAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    original_filename: str
    content_type: str
    size_bytes: int
    url: str
    width: int | None = None
    height: int | None = None
    folder: str | None = None
    alt_text: str = ""
    caption: str = ""
    credit: str = ""
    variants: dict[str, MediaAssetVariant] = Field(default_factory=dict)
    created_at: datetime


class MediaAssetListResponse(BaseModel):
    """Cursor-paginated page of media assets.

    ``next_cursor`` is the ``id`` to pass back as the ``cursor`` query
    param to fetch the next page (assets are returned newest-first, so
    the cursor advances toward smaller ids). ``None`` when there are no
    more rows. ``folders`` is the full set of distinct folder names in
    the library — independent of the current filter so the sidebar
    doesn't disappear when the user drills in.
    """

    items: list[MediaAssetRead]
    next_cursor: int | None = None
    folders: list[str] = Field(default_factory=list)
    total: int | None = None
    """Row count matching the filters. Only set for offset paging — cursor
    paging deliberately avoids the extra COUNT query."""


class MediaAssetUpdate(BaseModel):
    """The describable fields. The bytes are replaced through upload, not here."""

    alt_text: str | None = Field(default=None, max_length=500)
    caption: str | None = Field(default=None, max_length=500)
    credit: str | None = Field(default=None, max_length=200)


class MediaUsage(BaseModel):
    """One page referencing the asset."""

    page_id: int
    title: str
    slug: str
    status: str
    draft_only: bool


class MediaAssetDetail(BaseModel):
    """An asset plus where it is used.

    The usage list travels with the asset because every question worth asking on
    the detail screen — can I delete this, will editing the alt text change
    anything, who depends on it — is a question about that list.
    """

    asset: MediaAssetRead
    used_in: list[MediaUsage] = Field(default_factory=list)
    used_in_total: int = 0
