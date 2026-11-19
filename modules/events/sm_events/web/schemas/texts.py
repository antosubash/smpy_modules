"""An event's text in one language: request body and response."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from sm_events.core import constants
from sm_events.web.schemas._fields import MultiLine, SingleLine, TextSlug

Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=constants.TITLE_MAX),
    SingleLine,
]
Summary = Annotated[str, Field(max_length=constants.SUMMARY_MAX), MultiLine]
SeoTitle = Annotated[str, Field(max_length=constants.SEO_TITLE_MAX), SingleLine]
SeoDescription = Annotated[str, Field(max_length=constants.SEO_DESCRIPTION_MAX), MultiLine]


class TextIn(BaseModel):
    """One language's words. ``description`` is rich text: it is cleaned when the
    text is saved (not here), so a refusal carries its own error code."""

    title: Title
    slug: TextSlug | None = None
    summary: Summary | None = None
    description: str = ""
    seo_title: SeoTitle | None = None
    seo_description: SeoDescription | None = None
    noindex: bool = False


class TextOut(BaseModel):
    """What is stored; no input bounds, so an old row can always be shown."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    title: str
    summary: str | None
    description: str
    seo_title: str | None
    seo_description: str | None
    noindex: bool
