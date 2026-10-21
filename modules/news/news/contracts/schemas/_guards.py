"""Input checks shared by the article write DTOs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, model_validator

from news.safe_url import is_http_url, is_site_relative

HEADLINE_REQUIRED = "An article needs a headline."
NUL_MESSAGE = "Text cannot contain a NUL (\\x00) character."
ISO_REQUIRED = "Expected an ISO-8601 date-time with a UTC offset, e.g. 2026-01-31T09:00:00Z."


def clean_title(value: str | None) -> str | None:
    """Strip, as create does; a blank headline is refused."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError(HEADLINE_REQUIRED)
    return stripped


def canonical_url(value: str | None) -> str | None:
    """An absolute http(s) URL; ``""`` clears."""
    if value is None:
        return None
    value = value.strip()
    if value and not is_http_url(value):
        raise ValueError("The canonical URL must be a full http:// or https:// address.")
    return value


def og_image(value: str | None) -> str | None:
    """An absolute http(s) URL or a site path starting with ``/``; ``""`` clears."""
    if value is None:
        return None
    value = value.strip()
    if value and not (is_http_url(value) or is_site_relative(value)):
        raise ValueError(
            "The image must be a full http:// or https:// address, or a path starting with /."
        )
    return value


def aware_instant(value: Any) -> datetime | None:
    """An ISO-8601 string carrying an offset, as UTC; ``None`` clears.

    Left to pydantic, a number (or a numeric string) is Unix seconds, so
    ``{"publish_at": 1}`` schedules 1970 and goes live on the next tick, and a
    naive time is guessed to be UTC. Both are client bugs to name, not act on.
    SQLite drops an offset on write without converting, so the value is
    normalised here too.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(ISO_REQUIRED) from None
    else:
        raise ValueError(ISO_REQUIRED)
    if parsed.tzinfo is None:
        raise ValueError(ISO_REQUIRED)
    try:
        return parsed.astimezone(UTC)
    except OverflowError:  # 9999-12-31T23:59:59-05:00 has no UTC form
        raise ValueError(ISO_REQUIRED) from None


def optional_note(value: Any) -> Any:
    """Stripped; a note of only whitespace is no note at all.

    Runs before the field's own checks, so the length bound applies to the
    stripped note: padding never pushes a valid note over it, and a long run
    of spaces is no note rather than a 422. Anything but a string is left to
    pydantic to refuse.
    """
    return (value.strip() or None) if isinstance(value, str) else value


def _has_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_has_nul(k) or _has_nul(v) for k, v in value.items())
    if isinstance(value, list | tuple):
        return any(_has_nul(v) for v in value)
    return False


class NoNul(BaseModel):
    """Refuses a NUL byte in any text field, however deeply nested.

    Fine on SQLite, an error on Postgres — so a 422 here rather than a 500
    there.
    """

    @model_validator(mode="after")
    def _reject_nul(self) -> NoNul:
        if any(_has_nul(v) for v in self.__dict__.values()):
            raise ValueError(NUL_MESSAGE)
        return self
