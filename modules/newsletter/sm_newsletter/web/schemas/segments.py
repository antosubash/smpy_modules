"""Bodies of the segments API, parsed with ``parse_payload`` so a 422 never
echoes a rule value."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from sm_records.contracts.newsletter_admin import ListField

from sm_newsletter.core.constants import MAX_TYPE_KEY_LEN
from sm_newsletter.core.headers import check_header_text
from sm_newsletter.segments.rules import MAX_RULES, Rule

SegmentName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    AfterValidator(lambda v: check_header_text(v, field="name")),
]
ListKey = Annotated[str, Field(min_length=1, max_length=MAX_TYPE_KEY_LEN)]
Rules = Annotated[list[Rule], Field(max_length=MAX_RULES)]


class SegmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: SegmentName
    list_type_key: ListKey
    rules: Rules


class SegmentPatch(BaseModel):
    """The list cannot change; a field left out or sent as ``null`` stays as it is."""

    model_config = ConfigDict(extra="forbid")

    name: SegmentName | None = None
    rules: Rules | None = None


class SegmentPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    list_type_key: ListKey
    rules: Rules


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    list_type_key: str
    rules: list[Rule]
    updated_at: datetime | None
    # Read off the row only to fill ``updated_at``; never sent.
    created_at: datetime | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _created_is_last_change(self) -> SegmentOut:
        """The audit listener stamps ``updated_at`` on an update only, so a segment
        nobody has edited reports its creation as its last change."""
        if self.updated_at is None:
            self.updated_at = self.created_at
        return self


class CountOut(BaseModel):
    count: int


class ListFieldOut(ListField):
    ops: list[str]
