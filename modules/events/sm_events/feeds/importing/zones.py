"""Which zone a ``TZID`` names (Ruling 22): the IANA database or a fixed Windows-name table.

No zone definition in a file is ever used or evaluated: an unknown name is ``None``, which skips
the item (a file's ``VTIMEZONE`` could define any offsets; evaluating it is the zone bomb this
module refuses).
"""

from __future__ import annotations

import re
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = ["resolve_tzid"]

_ZONE_NAME: Final = re.compile(r"[A-Za-z0-9_+\-/]{1,64}", re.ASCII)
_TZONE_PREFIX: Final = "tzone://Microsoft/"


def _windows_table() -> dict[str, str]:
    from icalendar.timezone.windows_to_olson import WINDOWS_TO_OLSON

    return WINDOWS_TO_OLSON


def resolve_tzid(tzid: str | None) -> str | None:
    """The IANA zone a ``TZID`` names, else ``None`` (unknown: never evaluated, never guessed).

    An IANA name must be in the database; a Windows name (also as Outlook's
    ``tzone://Microsoft/<name>``) maps through ``icalendar``'s CLDR table."""
    if not tzid:
        return None
    name = tzid.removeprefix(_TZONE_PREFIX)
    if len(name) > 64 or not name.isprintable():
        return None
    if _ZONE_NAME.fullmatch(name):
        try:
            return ZoneInfo(name).key
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    mapped = _windows_table().get(name)
    if mapped is not None:
        try:
            return ZoneInfo(mapped).key
        except (ZoneInfoNotFoundError, ValueError, OSError):
            return None
    return None
