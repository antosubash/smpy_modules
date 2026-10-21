"""Field types shared by the write DTOs: instants and notes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BeforeValidator, StringConstraints

ISO_REQUIRED = "Expected an ISO-8601 date-time with a UTC offset, e.g. 2026-01-31T09:00:00Z."
NOTE_MAX = 2000


def _parse_aware(value: Any) -> Any:
    """An ISO-8601 string carrying an offset, as UTC — and nothing else.

    Left to pydantic, a number (or a numeric string) is Unix seconds, so
    ``{"publish_at": 1}`` schedules 1970 and a millisecond timestamp lands
    tens of millennia out; a naive time is silently read as UTC. Each of those
    is a client bug the API should name rather than act on.
    """
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
    return parsed.astimezone(UTC)


# A schedule instant on the way in.
AwareInstant = Annotated[datetime, BeforeValidator(_parse_aware)]


def _assume_utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


# Every instant is stored as UTC, but SQLite hands it back naive. Serialised
# without an offset, the editor's ``new Date()`` reads it as local time, so the
# schedule shows shifted and each re-save moves it again by the offset.
UtcInstant = Annotated[datetime, AfterValidator(_assume_utc)]

# Notes are stripped before their bounds apply, so a note of spaces is empty:
# a 422 where one is required, and no note at all where it is optional — the
# history panel never shows a blank reason.
RequiredNote = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOTE_MAX)
]
OptionalNote = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=NOTE_MAX)] | None,
    AfterValidator(lambda value: value or None),
]
