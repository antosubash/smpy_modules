"""Review queue bodies (bounded) and rows (not)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from sm_images.web.schemas.prompt import PromptResultOut


class ReviewIn(BaseModel):
    action: Literal["accept", "correct", "reject"]
    data: dict[str, Any] | None = None
    """The corrected value (``correct`` only), checked against the prompt's schema."""
    version: str = Field(min_length=1, max_length=64)
    """The ``version`` of the row the reviewer saw; another is a 409 ``review_stale``."""


class ReviewItemOut(PromptResultOut):
    version: str
    prompt_name: str
    output_schema: dict[str, Any] | None
    filename: str | None = None
    thumb_url: str | None = None
    group_key: str | None = None
    output_visible: bool = True


class ReviewPageOut(BaseModel):
    items: list[ReviewItemOut]
    next_cursor: int | None


class ReviewedOut(BaseModel):
    item: ReviewItemOut
    collection_id: uuid.UUID
