"""Where a JPEG's primary image ends, and whether it carries metadata (#356).

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

The same walk classifies every segment in the file, between scans too (Pillow's
own inventory stops at the first ``SOS``). Only the JFIF header without a
thumbnail, the ICC profile and the Adobe colour-transform segment are not
metadata; any other ``APPn`` (EXIF, XMP, IPTC, MPF, a ``JFXX`` thumbnail…) and
every comment are.
"""

from __future__ import annotations

import struct

_SOI, _EOI, _SOS, _COM = 0xD8, 0xD9, 0xDA, 0xFE
_APP0, _APP2, _APP14, _APP15 = 0xE0, 0xE2, 0xEE, 0xEF
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


def _is_metadata(marker: int, payload: bytes) -> bool:
    if marker == _COM:
        return True
    if not _APP0 <= marker <= _APP15:
        return False  # tables, frame and scan headers: the picture itself
    if marker == _APP0:
        # "JFIF\0", version, units, densities, then the thumbnail's width and height.
        return not (payload.startswith(b"JFIF\x00") and len(payload) >= 14
                    and payload[12] == payload[13] == 0)
    if marker == _APP2:
        return not payload.startswith(b"ICC_PROFILE\x00")
    if marker == _APP14:
        return not payload.startswith(b"Adobe")
    return True


def scan(data: bytes) -> tuple[int, bool]:
    """``(end, metadata)``: the offset just past the primary image's ``EOI``, and
    whether any segment before it is metadata."""
    metadata = False
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
            return pos + 2, metadata
        if marker in _STANDALONE:
            pos += 2
            continue
        if marker in (0x00, _SOI) or pos + 4 > len(data):
            raise JpegStructureError(f"unexpected marker {marker:#04x} at offset {pos}")
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        if length < 2 or pos + 2 + length > len(data):
            raise JpegStructureError(f"truncated segment {marker:#04x} at offset {pos}")
        metadata = metadata or _is_metadata(marker, data[pos + 4 : pos + 2 + length])
        pos += 2 + length
        if marker == _SOS:
            pos = _after_scan(data, pos)


def image_end(data: bytes) -> int:
    """The offset just past the primary image's ``EOI``."""
    return scan(data)[0]
