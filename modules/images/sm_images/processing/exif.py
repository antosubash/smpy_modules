"""EXIF extraction as a pure function (bytes in, :class:`ExifData` out).

Ported from the portal's ``pipeline/geolocation.py`` with its edge cases:
finite-rational checks (a ``0/0`` rational reads as NaN), S/W signs, altitude
below sea level, ``DateTimeOriginal`` falling back to ``DateTime``, NUL
stripping, camera-field truncation, and an exact (0, 0) fix meaning "no
location". The pipeline's ``exif`` step wraps this; precedence against manual
or imported coordinates is the executor's business, not this module's.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from PIL import Image

from sm_images._heif import register_heif

register_heif()

__all__ = ["ExifData", "read_exif"]

_EXIF_IFD: Final = 0x8769
_GPS_IFD: Final = 0x8825
_CAMERA_MAX: Final = 100


@dataclass(frozen=True)
class ExifData:
    """What the file's EXIF says; every field is ``None`` when absent or unusable.

    ``captured_at`` is timezone-aware when the file carries an offset tag
    (``OffsetTimeOriginal``, or ``OffsetTime`` for the ``DateTime`` fallback)
    and **naive** otherwise: a wall-clock time of unknown zone. The executor
    decides how to store a naive value.
    """

    lat: float | None = None
    lng: float | None = None
    altitude: float | None = None
    heading: float | None = None
    captured_at: datetime | None = None
    make: str | None = None
    model: str | None = None
    orientation: int | None = None


def _finite(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _degrees(value: Any) -> float | None:
    try:
        d, m, s = (float(p) for p in value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return _finite(d + m / 60.0 + s / 3600.0)


def _coordinates(gps: dict[int, Any]) -> tuple[float | None, float | None]:
    """Both or neither; out of range and exact (0, 0) are absent."""
    lat = _degrees(gps[2]) if 2 in gps and 1 in gps else None
    lng = _degrees(gps[4]) if 4 in gps and 3 in gps else None
    if lat is None or lng is None:
        return None, None
    if gps[1] == "S":
        lat = -lat
    if gps[3] == "W":
        lng = -lng
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0.0 and lng == 0.0):
        return None, None
    return lat, lng


def _altitude(gps: dict[int, Any]) -> float | None:
    alt = _finite(gps.get(6))
    if alt is None:
        return None
    return -alt if gps.get(5) in (1, b"\x01") else alt


def _heading(gps: dict[int, Any]) -> float | None:
    h = _finite(gps.get(17))
    return h if h is not None and 0 <= h <= 360 else None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.replace("\x00", "").strip()
    return cleaned[:_CAMERA_MAX] or None


def _captured_at(base: dict[int, Any], sub: dict[int, Any]) -> datetime | None:
    if sub.get(0x9003):
        raw, offset = sub.get(0x9003), sub.get(0x9011)
    else:
        raw, offset = base.get(0x0132), sub.get(0x9010)
    if not isinstance(raw, str):
        return None
    raw = raw.replace("\x00", "").strip()
    try:
        naive = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    if isinstance(offset, str):
        try:
            return datetime.strptime(
                f"{raw}{offset.replace(chr(0), '').strip()}", "%Y:%m:%d %H:%M:%S%z"
            )
        except ValueError:
            pass
    return naive


def read_exif(data: bytes) -> ExifData:
    """EXIF of ``data``; undecodable or EXIF-less input gives an empty :class:`ExifData`."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            exif = img.getexif()
            if not exif:
                return ExifData()
            base = dict(exif)
            sub = dict(exif.get_ifd(_EXIF_IFD))
            gps = dict(exif.get_ifd(_GPS_IFD))
    except Exception:
        return ExifData()
    lat, lng = _coordinates(gps)
    orientation = base.get(0x0112)
    return ExifData(
        lat=lat,
        lng=lng,
        altitude=_altitude(gps),
        heading=_heading(gps),
        captured_at=_captured_at(base, sub),
        make=_text(base.get(0x010F)),
        model=_text(base.get(0x0110)),
        orientation=orientation if isinstance(orientation, int) and 1 <= orientation <= 8 else None,
    )
