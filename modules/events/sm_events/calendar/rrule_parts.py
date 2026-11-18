"""The allow-listed RRULE parts, parsed and range-checked one by one. Pure.

Only these parts ever reach dateutil, and only as keyword arguments:
``FREQ INTERVAL COUNT UNTIL BYMONTH BYMONTHDAY BYDAY BYSETPOS WKST``. Anything
else is ``invalid_rrule`` with the part named in ``detail``; a sub-daily
frequency is ``rrule_frequency_refused``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sm_events.core import constants
from sm_events.core.errors import InvalidRule

FREQS = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
SUB_DAILY = ("SECONDLY", "MINUTELY", "HOURLY")
WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
ALLOWED = (
    "FREQ",
    "INTERVAL",
    "COUNT",
    "UNTIL",
    "BYMONTH",
    "BYMONTHDAY",
    "BYDAY",
    "BYSETPOS",
    "WKST",
)
_INT = re.compile(r"[+-]?[0-9]{1,4}", re.ASCII)
_BYDAY = re.compile(r"([+-]?[0-9]{1,2})?(MO|TU|WE|TH|FR|SA|SU)", re.ASCII)
_PREFIX = re.compile(r"RRULE:", re.IGNORECASE | re.ASCII)

ByDay = tuple[tuple[int, int | None], ...]


@dataclass(frozen=True)
class Parts:
    """The validated parts, minus UNTIL (which needs the timezone)."""

    freq: str
    interval: int = 1
    count: int | None = None
    until_text: str | None = None
    bymonth: tuple[int, ...] = ()
    bymonthday: tuple[int, ...] = ()
    byday: ByDay = ()
    bysetpos: tuple[int, ...] = ()
    wkst: int | None = None


def bad(part: str, why: str = "") -> InvalidRule:
    detail = f"{constants.INVALID_RRULE_DETAIL}: {part}"
    return InvalidRule(f"{detail} ({why})" if why else detail, code=constants.INVALID_RRULE_CODE)


def _int(value: str, part: str, lo: int, hi: int, *, signed: bool = False) -> int:
    if not _INT.fullmatch(value):
        raise bad(part)
    number = int(value)
    if signed and number == 0:
        raise bad(part, "zero")
    in_range = lo <= abs(number) <= hi if signed else lo <= number <= hi
    if not in_range:
        raise bad(part, f"{lo}..{hi}")
    return number


def _ints(value: str, part: str, hi: int, *, signed: bool) -> tuple[int, ...]:
    lo = 1
    return tuple(_int(v, part, lo, hi, signed=signed) for v in value.split(","))


def split(text: str) -> dict[str, str]:
    """``KEY=VALUE;...`` as an upper-cased dict; a repeat or a stray piece is refused.

    ASCII only and no whitespace is stripped: ``str.upper`` maps some non-ASCII
    letters onto ASCII ones and ``str.strip`` removes non-breaking spaces."""
    if not isinstance(text, str) or len(text) > constants.RRULE_MAX_LEN:
        raise bad("length", f"at most {constants.RRULE_MAX_LEN} characters")
    if not text.isascii():
        raise bad("characters", "ASCII only")
    prefix = _PREFIX.match(text)
    body = (text[prefix.end() :] if prefix else text).removesuffix(";")
    out: dict[str, str] = {}
    for piece in body.split(";"):
        key, sep, value = piece.partition("=")
        key, value = key.upper(), value.upper()
        if not sep or not key or not value:
            raise bad(piece or "empty")
        if key in out:
            raise bad(key, "repeated")
        out[key] = value
    return out


def _byday(value: str, freq: str) -> ByDay:
    found: set[tuple[int, int | None]] = set()
    for item in value.split(","):
        match = _BYDAY.fullmatch(item)
        if match is None:
            raise bad("BYDAY")
        ordinal = int(match.group(1)) if match.group(1) else None
        if ordinal is not None:
            if ordinal == 0 or abs(ordinal) > 5:
                raise bad("BYDAY", "ordinal -5..5")
            if freq not in ("MONTHLY", "YEARLY"):
                raise bad("BYDAY", "an ordinal needs MONTHLY or YEARLY")
        found.add((WEEKDAYS.index(match.group(2)), ordinal))
    return tuple(sorted(found, key=lambda d: (d[0], d[1] or 0)))


def parse_parts(text: str) -> Parts:
    raw = split(text)
    for key in raw:
        if key not in ALLOWED:
            raise bad(key)
    freq = raw.get("FREQ")
    if freq is None:
        raise bad("FREQ", "missing")
    if freq in SUB_DAILY:
        raise InvalidRule(
            f"{constants.RRULE_FREQUENCY_REFUSED_DETAIL}: {freq}",
            code=constants.RRULE_FREQUENCY_REFUSED_CODE,
        )
    if freq not in FREQS:
        raise bad("FREQ")
    interval = _int(raw.get("INTERVAL", "1"), "INTERVAL", 1, constants.RRULE_MAX_INTERVAL)
    count = None
    if "COUNT" in raw:
        count = _int(raw["COUNT"], "COUNT", 1, constants.RRULE_MAX_COUNT)
    if "COUNT" in raw and "UNTIL" in raw:
        raise bad("COUNT", "not together with UNTIL")
    bymonth = (
        tuple(sorted(set(_ints(raw["BYMONTH"], "BYMONTH", 12, signed=False))))
        if "BYMONTH" in raw
        else ()
    )
    bymonthday: tuple[int, ...] = ()
    if "BYMONTHDAY" in raw:
        days = set(_ints(raw["BYMONTHDAY"], "BYMONTHDAY", 31, signed=True))
        bymonthday = tuple(sorted(days, key=lambda n: (n < 0, n)))
    byday = _byday(raw["BYDAY"], freq) if "BYDAY" in raw else ()
    bysetpos: tuple[int, ...] = ()
    if "BYSETPOS" in raw:
        if not (bymonth or bymonthday or byday):
            raise bad("BYSETPOS", "needs another BY part")
        bysetpos = tuple(sorted(set(_ints(raw["BYSETPOS"], "BYSETPOS", 366, signed=True))))
    wkst = None
    if "WKST" in raw:
        if raw["WKST"] not in WEEKDAYS:
            raise bad("WKST")
        wkst = WEEKDAYS.index(raw["WKST"])
    return Parts(
        freq, interval, count, raw.get("UNTIL"), bymonth, bymonthday, byday, bysetpos, wkst
    )
