"""Category request bodies (bounded) and responses."""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sm_events.core import constants
from sm_events.web.schemas._fields import Color, Slug, lower_color

LocaleKey = Annotated[str, Field(min_length=1, max_length=constants.LOCALE_MAX)]
Names = Annotated[
    dict[LocaleKey, Annotated[str, Field(min_length=1, max_length=constants.CATEGORY_NAME_MAX)]],
    Field(min_length=1, max_length=20),
]


class CategoryCreate(BaseModel):
    slug: Slug | None = None
    names: Names
    color: Color | None = None

    _lower_color = field_validator("color", mode="before")(lower_color)


class CategoryPatch(BaseModel):
    """Every field optional. ``names`` replaces the whole map; ``color: null``
    clears the colour."""

    names: Names | None = None
    color: Color | None = None

    _lower_color = field_validator("color", mode="before")(lower_color)

    @model_validator(mode="after")
    def _no_null_names(self) -> CategoryPatch:
        if "names" in self.model_fields_set and self.names is None:
            raise ValueError("names cannot be null")
        return self


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    names: dict[str, str]
    color: str | None
