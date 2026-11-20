"""Validation shared by calendar and category request bodies."""

import unicodedata
from typing import Annotated, Any

from pydantic import AfterValidator, AwareDatetime, BeforeValidator, Field

from sm_events.calendar.times import supported_instant
from sm_events.core import constants, timezones
from sm_events.core.text_safety import (
    BIDI,
    CONTROL,
    INVISIBLE,
    LINE_SEPARATORS,
    MULTILINE_OK,
)
from sm_events.core.web_urls import is_site_image, is_web_url

Slug = Annotated[str, Field(max_length=constants.SLUG_MAX, pattern=constants.SLUG_PATTERN)]
TextSlug = Annotated[str, Field(max_length=constants.TEXT_SLUG_MAX, pattern=constants.SLUG_PATTERN)]
Color = Annotated[str, Field(pattern=constants.COLOR_PATTERN)]
SupportedInstant = Annotated[AwareDatetime, AfterValidator(supported_instant)]
"""A query-string instant with an offset, in the years a calendar means (else a 422)."""


def lower_color(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


def _reject_controls(value: Any, allowed: frozenset[str], extra: frozenset[str]) -> Any:
    if isinstance(value, str) and any(
        (unicodedata.category(ch) == CONTROL and ch not in allowed) or ch in extra for ch in value
    ):
        raise ValueError("control characters are not allowed")
    return value


def single_line(value: Any) -> Any:
    """Reject every control character, newline and tab included, plus the line
    and paragraph separators, the direction controls and the invisible spaces. Runs on
    the raw input, before any whitespace stripping can hide a trailing newline."""
    return _reject_controls(value, frozenset(), BIDI | LINE_SEPARATORS | INVISIBLE)


def multi_line(value: Any) -> Any:
    """Free text: newlines, tabs and the Unicode line separators are fine; NUL,
    the other controls and the direction controls are not."""
    return _reject_controls(value, MULTILINE_OK, BIDI)


SingleLine = BeforeValidator(single_line)
MultiLine = BeforeValidator(multi_line)


def known_timezone(value: str | None) -> str | None:
    if value is not None and not timezones.is_known(value):
        raise ValueError("not a known IANA timezone")
    return value


TimezoneName = Annotated[
    str, Field(min_length=1, max_length=constants.TZ_MAX), AfterValidator(known_timezone)
]

_URL_BAD = frozenset({"Cc", "Cf", "Zs", "Zl", "Zp"})


def http_url(value: str) -> str:
    """An absolute ``http`` or ``https`` URL with no whitespace, control character, user name
    or password in it; anything else (``javascript:``, ``data:``, a relative path) is refused."""
    if any(unicodedata.category(ch) in _URL_BAD for ch in value):
        raise ValueError("not a valid http(s) URL")
    if not is_web_url(value):  # the one rule: http(s), a host, no userinfo
        raise ValueError("only http and https URLs without a user name or password are allowed")
    return value


HttpUrl = Annotated[str, Field(max_length=constants.URL_MAX), AfterValidator(http_url)]


def image_ref(value: str) -> str:
    """An image reference: a path on the site (``/media/...``) or an absolute http(s) address. Which
    absolute addresses the site may show is decided where the origin is known (the write path)."""
    if value.startswith("/"):
        if not is_site_image(value):
            raise ValueError("not a valid path on this site")
        return value
    return http_url(value)


ImageRef = Annotated[str, Field(max_length=constants.URL_MAX), AfterValidator(image_ref)]
