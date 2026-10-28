"""Collection request bodies (bounded) and responses (not)."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints, field_validator
from sqlmodel import SQLModel

from sm_images import constants
from sm_images.contracts.schemas import CollectionRead
from sm_images.models import Visibility

Name = Annotated[str, StringConstraints(strip_whitespace=True, max_length=constants.NAME_MAX)]
Description = Annotated[str, StringConstraints(max_length=constants.DESCRIPTION_MAX)]
Slug = Annotated[str, StringConstraints(pattern=constants.SLUG_PATTERN)]


def _nonblank(value: str | None) -> str | None:
    if value is not None and not value:
        raise ValueError("name must not be blank")
    return value


class CollectionCreate(SQLModel):
    name: Name
    description: Description | None = None
    slug: Slug | None = None
    visibility: Visibility = Visibility.PRIVATE

    _name = field_validator("name")(_nonblank)


class CollectionUpdate(SQLModel):
    """PATCH body. ``visibility`` and ``slug`` are refused (422): visibility has
    ``PUT .../visibility``, and a slug is part of a public URL, so it is fixed.
    An explicit ``null`` name is ignored (the column is NOT NULL); a ``null``
    description clears it."""

    model_config = {"extra": "forbid"}

    name: Name | None = None
    description: Description | None = None

    _name = field_validator("name")(_nonblank)


class VisibilityUpdate(SQLModel):
    visibility: Visibility


class CollectionOut(CollectionRead):
    is_owner: bool


class CollectionPageOut(SQLModel):
    items: list[CollectionOut]
    next_cursor: str | None
    total: int | None


class ShareCandidate(SQLModel):
    id: str
    display_name: str
    email: str
