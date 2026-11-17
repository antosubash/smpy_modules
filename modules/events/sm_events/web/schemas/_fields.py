"""Validation shared by calendar and category request bodies."""

from typing import Annotated, Any

from pydantic import Field

from sm_events.core import constants

Slug = Annotated[str, Field(max_length=constants.SLUG_MAX, pattern=constants.SLUG_PATTERN)]
Color = Annotated[str, Field(pattern=constants.COLOR_PATTERN)]


def lower_color(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value
