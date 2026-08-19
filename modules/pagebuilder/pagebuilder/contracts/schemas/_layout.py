"""Site layout and its revisions."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from pagebuilder.models import PageStatus, RevisionEvent

PuckData = dict[str, Any]


class LayoutUpdate(BaseModel):
    """``None`` leaves a slot alone; an empty Puck doc clears it."""

    header_data: PuckData | None = None
    footer_data: PuckData | None = None
    note: str | None = Field(default=None, max_length=2000)


class LayoutRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime | None


class LayoutDetail(LayoutRead):
    header_data: PuckData
    footer_data: PuckData


class LayoutRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    layout_id: int
    note: str | None
    created_at: datetime
    created_by: str | None


class LayoutRevisionDetail(LayoutRevisionRead):
    header_data: PuckData
    footer_data: PuckData


class LayoutRevisionListResponse(BaseModel):
    items: list[LayoutRevisionRead]


