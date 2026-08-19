"""Uploaded files and the metadata that describes them."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from simple_module_db.mixins import AuditMixin
from sqlalchemy import JSON, Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from pagebuilder.models._base import Base


class MediaAsset(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """An uploaded media file stored on local disk.

    The bytes themselves live under :attr:`PagebuilderSettings.media_root`;
    this row holds the metadata + sanitized filename used to build the
    public URL.

    ``width`` / ``height`` are populated for raster images so the Image
    block can emit them on ``<img>`` and avoid layout shift; ``variants``
    lists server-generated thumbnails / webp transcodes keyed by a stable
    label (e.g. ``"w640"``, ``"webp"``) — each entry stores at minimum
    ``{filename, width, height, content_type}``.
    """

    __tablename__ = "pagebuilder_media"

    id: int | None = Field(default=None, primary_key=True)
    filename: str = Field(max_length=300, unique=True, index=True)
    original_filename: str = Field(max_length=300)
    content_type: str = Field(max_length=120)
    size_bytes: int = Field(default=0)
    width: int | None = Field(default=None)
    height: int | None = Field(default=None)
    alt_text: str = Field(default="", max_length=500)
    """What the image says, for anyone not seeing it.

    On the asset rather than per-placement: it describes the picture, not the
    layout, and asking again at every placement is how alt text ends up empty
    everywhere.
    """

    caption: str = Field(default="", max_length=500)
    """Optional line rendered under the image."""

    credit: str = Field(default="", max_length=200)
    """Photographer or source. Separate from the caption, which gets rewritten
    per context while the credit does not."""

    folder: str | None = Field(default=None, max_length=300, index=True)
    variants: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )


