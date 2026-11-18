"""Validation shared by calendar and category request bodies."""

import unicodedata
from typing import Annotated, Any

from pydantic import AfterValidator, AwareDatetime, BeforeValidator, Field

from sm_events.calendar.times import supported_instant
from sm_events.core import constants, timezones
from sm_events.core.web_urls import is_web_url

Slug = Annotated[str, Field(max_length=constants.SLUG_MAX, pattern=constants.SLUG_PATTERN)]
TextSlug = Annotated[str, Field(max_length=constants.TEXT_SLUG_MAX, pattern=constants.SLUG_PATTERN)]
Color = Annotated[str, Field(pattern=constants.COLOR_PATTERN)]
SupportedInstant = Annotated[AwareDatetime, AfterValidator(supported_instant)]
"""A query-string instant with an offset, in the years a calendar means (else a 422)."""

_CONTROL = "Cc"
"""Unicode category of the C0 and C1 controls, NUL, tab, newline and DEL."""
_MULTILINE_OK = frozenset("\n\r\t")
_BIDI = frozenset("\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
"""Direction marks and embeddings/overrides/isolates: they reorder the text
around a name when it is shown in a sentence."""
_LINE_SEPARATORS = frozenset("\u2028\u2029")
_INVISIBLE = frozenset("\u200b\u2060\ufeff")
"""Zero-width space, word joiner and BOM: they make a name that looks empty or
that differs from another one by nothing visible. U+200C and U+200D (the
zero-width non-joiner and joiner) stay allowed: Persian, Indic scripts and emoji
sequences need them."""


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
    and paragraph separators, the direction controls and the invisible spaces. Runs on
    the raw input, before any whitespace stripping can hide a trailing newline."""
    return _reject_controls(value, frozenset(), _BIDI | _LINE_SEPARATORS | _INVISIBLE)


def strip_unsafe(value: str, *, newlines: bool = False) -> str:
    """``value`` without what :func:`single_line` would refuse (``newlines``: what
    :func:`multi_line` would refuse), for text taken from somewhere that is not a person typing
    it (an imported file), where refusing the whole value would lose an event over one stray
    control character."""
    allowed = _MULTILINE_OK if newlines else frozenset()
    extra = _BIDI if newlines else _BIDI | _LINE_SEPARATORS | _INVISIBLE
    return "".join(
        ch
        for ch in value
        if not ((unicodedata.category(ch) == _CONTROL and ch not in allowed) or ch in extra)
    )


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
