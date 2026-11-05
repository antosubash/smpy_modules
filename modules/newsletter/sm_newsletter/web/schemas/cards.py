"""Bodies of the card, media and card-refresh routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from sm_newsletter.content.integrations.hits import MAX_SOURCE_ID

BlockId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class CardHitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: Literal["article", "page"]
    source_id: int
    title: str
    excerpt: str
    image_url: str
    url: str
    locale: str


class MediaHitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    url: str


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["article", "page"]
    source_id: Annotated[StrictInt, Field(gt=0, le=MAX_SOURCE_ID)]


class CardSnapshot(BaseModel):
    """A card block's props, ready to drop into the body."""

    id: str
    source_id: int
    title: str
    excerpt: str
    image_url: str
    url: str
    locale: str
    snapshot_at: datetime


class RefreshRequest(BaseModel):
    """``expected_revision`` is the revision the editor read (409 ``stale``)."""

    model_config = ConfigDict(extra="forbid")

    block_id: BlockId
    expected_revision: StrictInt
