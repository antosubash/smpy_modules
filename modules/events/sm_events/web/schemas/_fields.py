"""Validation shared by calendar and category request bodies."""

import unicodedata
from typing import Annotated, Any

from pydantic import BeforeValidator, Field

from sm_events.core import constants

Slug = Annotated[str, Field(max_length=constants.SLUG_MAX, pattern=constants.SLUG_PATTERN)]
Color = Annotated[str, Field(pattern=constants.COLOR_PATTERN)]

_CONTROL = "Cc"
"""Unicode category of the C0 and C1 controls, NUL, tab, newline and DEL."""
_MULTILINE_OK = frozenset("\n\r\t")


def lower_color(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


def _reject_controls(value: Any, allowed: frozenset[str]) -> Any:
    if isinstance(value, str) and any(
        unicodedata.category(ch) == _CONTROL and ch not in allowed for ch in value
    ):
        raise ValueError("control characters are not allowed")
    return value


def single_line(value: Any) -> Any:
    """Reject every control character, newline and tab included. Runs on the
    raw input, before any whitespace stripping can hide a trailing newline."""
    return _reject_controls(value, frozenset())


def multi_line(value: Any) -> Any:
    """Free text: newlines and tabs are fine, NUL and the other controls are not."""
    return _reject_controls(value, _MULTILINE_OK)


SingleLine = BeforeValidator(single_line)
MultiLine = BeforeValidator(multi_line)
