"""Where a JPEG's primary image ends, so a trailer after it can go (#356).

Phones append data after a JPEG's end-of-image marker (``FFD9``): a Samsung
motion photo carries a video and an ``SEFT`` trailer that can hold metadata,
and decoders never read it. Cutting the file at the true end is lossless.

The end is found by walking the marker segments from ``SOI``: each segment's
length is skipped whole, so an ``FFD9`` inside one (an EXIF thumbnail in
``APP1`` ends with one) is never mistaken for the end. After ``SOS`` the
entropy-coded data is scanned, where ``FF00`` is a stuffed byte, ``FFD0`` to
``FFD7`` a restart marker and ``FFFF`` fill, and any other marker resumes the
segment walk (a progressive JPEG has several scans). A file that does not walk
cleanly to ``EOI`` raises :class:`JpegStructureError`; the caller re-saves it
instead (truncated files from cameras and scanners are common).
"""

from __future__ import annotations

import struct

_SOI, _EOI, _SOS = 0xD8, 0xD9, 0xDA
# Markers with no length field: TEM and the restart markers.
_STANDALONE = frozenset({0x01, *range(0xD0, 0xD8)})


class JpegStructureError(ValueError):
    """The marker stream is truncated or not a JPEG."""


def _after_scan(data: bytes, pos: int) -> int:
    """The offset of the first real marker after the entropy-coded data at *pos*."""
    while True:
        pos = data.find(b"\xff", pos)
        if pos < 0 or pos + 1 >= len(data):
            raise JpegStructureError("entropy-coded data runs past the end")
        following = data[pos + 1]
        if following == 0x00 or following in _STANDALONE:
            pos += 2  # a stuffed byte or a restart marker: still scan data
        elif following == 0xFF:
            pos += 1  # fill
        else:
            return pos


def image_end(data: bytes) -> int:
    """The offset just past the primary image's ``EOI``."""
    if not data.startswith(b"\xff\xd8"):
        raise JpegStructureError("not a JPEG")
    pos = 2
    while True:
        if pos + 2 > len(data) or data[pos] != 0xFF:
            raise JpegStructureError(f"no marker at offset {pos}")
        while pos + 1 < len(data) and data[pos + 1] == 0xFF:
            pos += 1  # fill bytes before a marker
        if pos + 2 > len(data):
            raise JpegStructureError("truncated marker")
        marker = data[pos + 1]
        if marker == _EOI:
            return pos + 2
        if marker in _STANDALONE:
            pos += 2
            continue
        if marker in (0x00, _SOI) or pos + 4 > len(data):
            raise JpegStructureError(f"unexpected marker {marker:#04x} at offset {pos}")
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        if length < 2 or pos + 2 + length > len(data):
            raise JpegStructureError(f"truncated segment {marker:#04x} at offset {pos}")
        pos += 2 + length
        if marker == _SOS:
            pos = _after_scan(data, pos)


def strip_trailer(data: bytes) -> bytes | None:
    """*data* cut at its primary image's end, or ``None`` when nothing follows it."""
    end = image_end(data)
    return data[:end] if end < len(data) else None
