"""Small readers over one ``VEVENT``'s properties, shared by the mapper (Rulings 22 to 27).

Pure: no database, no clock. ``count_dropped`` counts what is not imported by property name and
never stores a value (an ``ATTENDEE`` carries an address): an ``X-`` property is counted as
``X-*`` and anything unnamed as ``other``, so a file cannot invent report keys.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Final

from sm_events.core import constants
from sm_events.feeds.importing.scan import Prop, RawEvent
from sm_events.feeds.importing.text import clean_title, unescape

__all__ = [
    "PRIVATE",
    "category_of",
    "count_dropped",
    "geo_of",
    "one",
    "sequence_of",
    "text_of",
    "title_of",
    "uid_of",
]

USED: Final = frozenset(
    [
        "UID",
        "DTSTART",
        "DTEND",
        "DURATION",
        "SUMMARY",
        "DESCRIPTION",
        "URL",
        "LOCATION",
        "GEO",
        "STATUS",
        "CATEGORIES",
        "CLASS",
        "RRULE",
        "EXDATE",
        "RECURRENCE-ID",
    ]
)
QUIET: Final = frozenset(["DTSTAMP", "CREATED", "LAST-MODIFIED", "SEQUENCE", "TRANSP"])
REPORTED: Final = frozenset(["ATTENDEE", "ORGANIZER", "ATTACH", "RELATED-TO", "X-ALT-DESC"])
PRIVATE: Final = frozenset({"PRIVATE", "CONFIDENTIAL"})


def one(props: Sequence[Prop], name: str) -> Prop | None:
    return next((p for p in props if p.name == name), None)


def text_of(props: Sequence[Prop], name: str) -> str:
    prop = one(props, name)
    return unescape(prop.value) if prop is not None else ""


def uid_of(props: Sequence[Prop]) -> tuple[str, bool]:
    prop = one(props, "UID")
    if prop is not None and prop.value.strip():
        return prop.value, False
    start = one(props, "DTSTART")
    line = (
        ""
        if start is None
        else ";".join([start.name, *(f"{k}={v}" for k, v in start.params.items())])
        + ":"
        + start.value
    )
    digest = hashlib.sha256(f"{line}\n{text_of(props, 'SUMMARY')}".encode()).hexdigest()[:32]
    return f"{digest}@import{constants.UID_SUFFIX}", True


def sequence_of(raw: RawEvent) -> int:
    prop = one(raw.props, "SEQUENCE")
    try:
        return max(0, min(int(prop.value.strip()), 10**9)) if prop is not None else 0
    except ValueError:
        return 0


def count_dropped(raw: RawEvent, dropped: Counter[str]) -> None:
    for prop in raw.props:
        if prop.name in USED or prop.name in QUIET:
            continue
        dropped[
            prop.name if prop.name in REPORTED else "X-*" if prop.name.startswith("X-") else "other"
        ] += 1
    dropped.update(raw.children)


def geo_of(props: Sequence[Prop]) -> tuple[float | None, float | None]:
    prop = one(props, "GEO")
    parts = prop.value.split(";") if prop is not None else []
    if len(parts) != 2:
        return None, None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        return None, None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return lat, lon


def category_of(
    props: Sequence[Prop], categories: Mapping[str, uuid.UUID]
) -> tuple[uuid.UUID | None, bool]:
    prop = one(props, "CATEGORIES")
    if prop is None:
        return None, False
    for name in prop.value.split(","):
        found = categories.get(unescape(name).strip().lower())
        if found is not None:
            return found, False
    return None, True


def title_of(props: Sequence[Prop]) -> tuple[str, tuple[str, ...]]:
    return clean_title(text_of(props, "SUMMARY"))
