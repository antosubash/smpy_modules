"""Group request bodies (bounded) and responses (not)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from sm_images import constants
from sm_images.imports.filename_pattern import MAX_PATTERN_LENGTH
from sm_images.schemas.image import ImageOut

GroupKey = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=constants.GROUP_KEY_MAX)
]


class GroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: GroupKey
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class GroupUpdate(BaseModel):
    """Only the fields sent change; ``name``/``description`` accept ``null`` to clear."""

    model_config = ConfigDict(extra="forbid")

    key: GroupKey | None = None
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class GroupOut(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    key: str
    name: str | None
    description: str | None
    image_count: int
    members: list[ImageOut]
    """In role order (the collection's ``group_roles``); the list response carries
    the first few, the detail all of them."""


class GroupPageOut(BaseModel):
    items: list[GroupOut]
    next_cursor: str | None


class RegroupIn(BaseModel):
    """``pattern`` needs a ``(?P<group>...)`` part and may have a ``(?P<role>...)``."""

    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(min_length=1, max_length=MAX_PATTERN_LENGTH)
    reassign: bool = False
    """Also regroup images that already have a group (default: leave them)."""
    dry_run: bool = False


class RegroupOut(BaseModel):
    """What a regroup did (or, for a preview, would do)."""

    dry_run: bool
    scanned: int
    matched: int
    no_match: int
    timed_out: int
    already_grouped: int
    """Matched, but left alone: they have a group and ``reassign`` was off."""
    unchanged: int
    """Matched and already exactly as derived."""
    assigned: int
    """Images actually changed (a write that lost a race is not counted)."""
    groups_created: int
    """Groups this regroup inserted."""
    groups_existing: int
    """Groups it used that were already there (including one a competing writer inserted)."""


class RegroupJobOut(RegroupOut):
    """A background regroup's progress: the counters so far and its state."""

    id: uuid.UUID
    collection_id: uuid.UUID
    status: Literal["running", "completed", "failed", "cancelled"]
    error_code: str | None
    pattern: str
    reassign: bool
    created_at: datetime | None
    finished_at: datetime | None


class RegroupStarted(BaseModel):
    job_id: uuid.UUID
