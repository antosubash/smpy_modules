"""Values out of a GeoJSON feature: properties, coordinates, timestamps.

Ported from the portal's ``geojson_values.py``, with the fixes the porting map
asks for (static findings 4): coordinates are rejected unless finite and in
range, a timestamp is always timezone-aware (naive means UTC), and the
"centroid" of a line or polygon is documented for what it is - a
representative point (the middle vertex of a line, the vertex mean of a ring),
not an area centroid.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

__all__ = ["coordinates", "lookup", "parse_datetime"]

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S", "%d-%m-%Y", "%m/%d/%Y")
_MS_THRESHOLD = 1e11
_TIMESTAMP_MAX = 10**15
"""Beyond any real timestamp (seconds or milliseconds): refused before ``float``."""
_DATE_TEXT_MAX = 64
"""Longest date text worth parsing; longer is no date (and never reaches ``int``)."""
"""A number above this is a timestamp in milliseconds (1e11 s is the year 5138)."""


def lookup(properties: dict[str, Any], path: str | None) -> Any:
    """``properties[path]``, else the dotted path into nested objects."""
    if not path or not properties:
        return None
    if path in properties:
        return properties[path]
    value: Any = properties
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _valid(lat: float | None, lng: float | None) -> tuple[float | None, float | None]:
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None, None
    return lat, lng


def _point(pos: Any) -> tuple[float | None, float | None]:
    if not isinstance(pos, list | tuple) or len(pos) < 2:
        return None, None
    return _number(pos[1]), _number(pos[0])


def _mean(points: list[tuple[float | None, float | None]]) -> tuple[float | None, float | None]:
    good = [(a, b) for a, b in points if a is not None and b is not None]
    if not good:
        return None, None
    return sum(a for a, _ in good) / len(good), sum(b for _, b in good) / len(good)


def _middle(line: Any) -> tuple[float | None, float | None]:
    return _point(line[len(line) // 2]) if isinstance(line, list) and line else (None, None)


def _ring(polygon: Any) -> tuple[float | None, float | None]:
    if not isinstance(polygon, list) or not polygon or not isinstance(polygon[0], list):
        return None, None
    ring = polygon[0]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]  # the closing vertex would count twice
    return _mean([_point(p) for p in ring])


def _geometry(geometry: dict[str, Any]) -> tuple[float | None, float | None]:
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if not isinstance(coords, list) or not coords:
        return None, None
    if kind == "Point":
        return _point(coords)
    if kind == "MultiPoint":
        return _mean([_point(p) for p in coords])
    if kind == "LineString":
        return _middle(coords)
    if kind == "MultiLineString":
        return _mean([_middle(line) for line in coords])
    if kind == "Polygon":
        return _ring(coords)
    if kind == "MultiPolygon":
        return _mean([_ring(poly) for poly in coords])
    return None, None


def coordinates(
    properties: dict[str, Any],
    geometry: dict[str, Any] | None,
    lat_prop: str | None,
    lng_prop: str | None,
) -> tuple[float | None, float | None]:
    """``(lat, lng)`` from the mapped properties, else the geometry; both or neither.
    ``(0, 0)`` is a real location."""
    if lat_prop and lng_prop:
        found = _valid(_number(lookup(properties, lat_prop)), _number(lookup(properties, lng_prop)))
        if found[0] is not None:
            return found
    if isinstance(geometry, dict):
        return _valid(*_geometry(geometry))
    return None, None


def _aware(value: datetime) -> datetime | None:
    """``value`` in UTC (naive is read as UTC); ``None`` when the conversion
    leaves datetime's range (``0001-01-01T00:00+01:00``) - what the database
    would otherwise fail on, long after parsing."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError):
        return None


def parse_datetime(value: Any) -> datetime | None:
    """ISO 8601 (``Z`` too), a few common layouts, or a Unix timestamp in seconds
    or milliseconds, always in UTC; ``None`` when unreadable or out of range."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, int | float):
        if isinstance(value, int) and abs(value) > _TIMESTAMP_MAX:
            return None  # a huge integer: ``float()`` would overflow
        seconds = float(value)
        if not math.isfinite(seconds) or abs(seconds) > _TIMESTAMP_MAX:
            return None
        if abs(seconds) > _MS_THRESHOLD:
            seconds /= 1000
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if len(text) > _DATE_TEXT_MAX:
        return None
    try:
        return _aware(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except (ValueError, OverflowError):
        pass
    for fmt in _DATE_FORMATS:
        try:
            return _aware(datetime.strptime(text, fmt))
        except (ValueError, OverflowError):
            continue
    return None
