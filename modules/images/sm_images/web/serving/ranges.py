"""One HTTP ``Range: bytes=…`` against an object of known size.

Ported from the portal's ``range_response.py``. Only a single byte range is
honoured: a multi-range header, another unit or a malformed spec is ignored and
the whole object served with 200, which RFC 9110 allows. A well-formed range
that starts past the end raises :class:`RangeNotSatisfiable` (answer 416).
A position of any length is well-formed: a huge first-pos is a 416, a huge
last-pos is clamped to the end, and a huge suffix is the whole object.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ByteRange", "RangeNotSatisfiable", "parse_range"]

_UNIT = "bytes="


class RangeNotSatisfiable(Exception):  # noqa: N818 - HTTP vocabulary, deliberately
    """The range names bytes outside the object."""


@dataclass(frozen=True)
class ByteRange:
    """An inclusive byte range."""

    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


_MAX_DIGITS = 19
"""More digits than any object can have bytes. A longer number is still a
well-formed position (RFC 9110 sets no limit), so it is read as "past every
end" rather than converted: ``int()`` of a few thousand digits raises."""
_HUGE = 10**_MAX_DIGITS


def _int(value: str) -> int | None:
    value = value.strip()
    if not (value.isascii() and value.isdigit()):
        return None
    significant = value.lstrip("0") or "0"
    return _HUGE if len(significant) > _MAX_DIGITS else int(significant)


def _suffix(raw: str, size: int) -> ByteRange | None:
    """``-N``: the last N bytes."""
    n = _int(raw)
    if n is None:
        return None
    if n == 0 or size == 0:
        raise RangeNotSatisfiable
    return ByteRange(max(0, size - n), size - 1)


def _from(raw_start: str, raw_end: str, size: int) -> ByteRange | None:
    """``A-`` or ``A-B``: from A to B (clamped to the end) or to the end."""
    start = _int(raw_start)
    if start is None:
        return None
    end = size - 1
    if raw_end.strip():
        parsed = _int(raw_end)
        if parsed is None or parsed < start:
            return None
        end = min(parsed, size - 1)
    if start >= size:
        raise RangeNotSatisfiable
    return ByteRange(start, end)


def parse_range(header: str | None, size: int) -> ByteRange | None:
    """The range to serve, or ``None`` for the whole object."""
    if not header:
        return None
    header = header.strip()
    if not header.startswith(_UNIT):
        return None
    spec = header.removeprefix(_UNIT).strip()
    if "," in spec or "-" not in spec:
        return None
    raw_start, raw_end = spec.split("-", 1)
    if not raw_start.strip():
        return _suffix(raw_end, size)
    return _from(raw_start, raw_end, size)
