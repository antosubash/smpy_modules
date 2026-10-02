"""Input checks shared by the article write DTOs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator

from news.safe_url import is_http_url, is_site_relative

HEADLINE_REQUIRED = "An article needs a headline."
NUL_MESSAGE = "Text cannot contain a NUL (\\x00) character."


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
