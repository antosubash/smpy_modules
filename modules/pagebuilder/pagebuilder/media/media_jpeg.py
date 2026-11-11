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
from typing import NamedTuple

_SOI, _EOI, _SOS, _COM = 0xD8, 0xD9, 0xDA, 0xFE
_APP0, _APP2, _APP14, _APP15 = 0xE0, 0xE2, 0xEE, 0xEF
# Markers with no length field: TEM and the restart markers.
_STANDALONE = frozenset({0x01, *range(0xD0, 0xD8)})


class JpegStructureError(ValueError):
    """The marker stream is truncated or not a JPEG."""


class JpegScan(NamedTuple):
    end: int
    """The offset just past the primary image's ``EOI``."""
    metadata: bool
    """Whether any segment before it is metadata."""
    icc: bytes | None
    """The ICC profile from every ``APP2`` fragment, wherever it sits."""


_ICC = b"ICC_PROFILE\x00"
_JFIF_SIZE = 14  # "JFIF\0", version, units, densities, thumbnail width and height
_ADOBE_SIZE = 12  # "Adobe", version, two flag words, colour transform


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
    # Exactly the defined size: a decoder ignores bytes appended inside one.
    if marker == _APP0:  # no thumbnail: its width and height are the last two bytes
        return not (payload.startswith(b"JFIF\x00") and len(payload) == _JFIF_SIZE
                    and payload[12] == payload[13] == 0)
    if marker == _APP2:
        return not payload.startswith(_ICC)
    if marker == _APP14:
        return not (payload.startswith(b"Adobe") and len(payload) == _ADOBE_SIZE)
    return True


def _icc_profile(fragments: list[bytes]) -> bytes | None:
    """The profile, from ``ICC_PROFILE\\0``, sequence number, count, data.

    ``None`` when the fragments are not exactly numbers 1 to count, once each.
    """
    if not fragments:
        return None
    count = fragments[0][13] if len(fragments[0]) > 13 else 0
    numbered = {}
    for fragment in fragments:
        if len(fragment) < 14 or fragment[13] != count or fragment[12] in numbered:
            return None
        numbered[fragment[12]] = fragment[14:]
    if sorted(numbered) != list(range(1, count + 1)):
        return None
    return b"".join(numbered[number] for number in sorted(numbered))


def scan(data: bytes) -> JpegScan:
    """Walk the primary image to its ``EOI``; see :class:`JpegScan`.

    ICC fragments that do not assemble count as metadata (and give no profile).
    """
    metadata = False
    fragments: list[bytes] = []
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
            icc = _icc_profile(fragments)
            return JpegScan(pos + 2, metadata or (bool(fragments) and icc is None), icc)
        if marker in _STANDALONE:
            pos += 2
            continue
        if marker in (0x00, _SOI) or pos + 4 > len(data):
            raise JpegStructureError(f"unexpected marker {marker:#04x} at offset {pos}")
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        if length < 2 or pos + 2 + length > len(data):
            raise JpegStructureError(f"truncated segment {marker:#04x} at offset {pos}")
        payload = data[pos + 4 : pos + 2 + length]
        metadata = metadata or _is_metadata(marker, payload)
        if marker == _APP2 and payload.startswith(_ICC):
            fragments.append(payload)
        pos += 2 + length
        if marker == _SOS:
            pos = _after_scan(data, pos)


def image_end(data: bytes) -> int:
    """The offset just past the primary image's ``EOI``."""
    return scan(data).end
