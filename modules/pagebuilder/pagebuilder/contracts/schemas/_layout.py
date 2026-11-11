"""Site layout and its revisions."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict

from pagebuilder.content.links import checked
from pagebuilder.contracts.schemas._fields import OptionalNote

PuckData = dict[str, Any]
# Checked on the way in, like a page's draft (#354): a header or footer link
# outside the allow-list is a 422 naming the block and the field.
CheckedPuckData = Annotated[PuckData, AfterValidator(checked)]


class LayoutUpdate(BaseModel):
    """``None`` leaves a slot alone; an empty Puck doc clears it."""

    header_data: CheckedPuckData | None = None
    footer_data: CheckedPuckData | None = None
    note: OptionalNote = None


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
