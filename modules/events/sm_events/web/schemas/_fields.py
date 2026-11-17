"""Validation shared by calendar and category request bodies."""

import unicodedata
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import AfterValidator, BeforeValidator, Field

from sm_events.core import constants, timezones

Slug = Annotated[str, Field(max_length=constants.SLUG_MAX, pattern=constants.SLUG_PATTERN)]
TextSlug = Annotated[str, Field(max_length=constants.TEXT_SLUG_MAX, pattern=constants.SLUG_PATTERN)]
Color = Annotated[str, Field(pattern=constants.COLOR_PATTERN)]

_CONTROL = "Cc"
"""Unicode category of the C0 and C1 controls, NUL, tab, newline and DEL."""
_MULTILINE_OK = frozenset("\n\r\t")
_BIDI = frozenset("\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
"""Direction marks and embeddings/overrides/isolates: they reorder the text
around a name when it is shown in a sentence."""
_LINE_SEPARATORS = frozenset("\u2028\u2029")


def lower_color(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


def _reject_controls(value: Any, allowed: frozenset[str], extra: frozenset[str]) -> Any:
    if isinstance(value, str) and any(
        (unicodedata.category(ch) == _CONTROL and ch not in allowed) or ch in extra for ch in value
    ):
        raise ValueError("control characters are not allowed")
    return value


def single_line(value: Any) -> Any:
    """Reject every control character, newline and tab included, plus the line
    and paragraph separators and the direction controls. Runs on the raw input,
    before any whitespace stripping can hide a trailing newline."""
    return _reject_controls(value, frozenset(), _BIDI | _LINE_SEPARATORS)


def multi_line(value: Any) -> Any:
    """Free text: newlines, tabs and the Unicode line separators are fine; NUL,
    the other controls and the direction controls are not."""
    return _reject_controls(value, _MULTILINE_OK, _BIDI)


SingleLine = BeforeValidator(single_line)
MultiLine = BeforeValidator(multi_line)


def known_timezone(value: str | None) -> str | None:
    if value is not None and not timezones.is_known(value):
        raise ValueError("not a known IANA timezone")
    return value


TimezoneName = Annotated[
    str, Field(min_length=1, max_length=constants.TZ_MAX), AfterValidator(known_timezone)
]

_HTTP_SCHEMES = frozenset({"http", "https"})
_URL_BAD = frozenset({"Cc", "Cf", "Zs", "Zl", "Zp"})


def http_url(value: str) -> str:
    """An absolute ``http`` or ``https`` URL with no whitespace or control
    character in it; anything else (``javascript:``, ``data:``, a relative path)
    is refused."""
    if any(unicodedata.category(ch) in _URL_BAD for ch in value):
        raise ValueError("not a valid http(s) URL")
    try:
        parts = urlsplit(value)
    except ValueError:
        raise ValueError("not a valid http(s) URL") from None
    if parts.scheme.lower() not in _HTTP_SCHEMES or not parts.hostname:
        raise ValueError("only http and https URLs are allowed")
    return value


HttpUrl = Annotated[str, Field(max_length=constants.URL_MAX), AfterValidator(http_url)]
