"""Removing a WebP's metadata at the RIFF level, without re-encoding it (#356).

A WebP is a RIFF container: ``RIFF`` <size> ``WEBP`` and then chunks, each a
four-character type, a little-endian size and a payload padded to an even
length. The picture is in ``VP8 `` (lossy) or ``VP8L`` (lossless), with
``ALPH`` for a lossy picture's transparency, and an animation is ``ANIM`` plus
one ``ANMF`` per frame. ``VP8X`` is the extended header, whose flags say which
optional chunks follow.

Cleaning copies the chunks that draw the picture (:data:`KEPT`, the ICC profile
``ICCP`` among them) byte for byte and leaves the rest out: ``EXIF``, ``XMP ``
and anything unknown. The ``VP8X`` EXIF and XMP flags are cleared and the RIFF
size rewritten. A lossy WebP loses nothing, static or animated. Anything that
does not parse as a RIFF WebP is refused (:class:`WebpStructureError`).
"""

from __future__ import annotations

import struct

KEPT = frozenset({b"VP8X", b"ICCP", b"ANIM", b"ANMF", b"ALPH", b"VP8 ", b"VP8L"})
# VP8X flags byte: Rsv(2) ICC Alpha EXIF XMP Animation Rsv(1).
_EXIF_FLAG = 0x08
_XMP_FLAG = 0x04
_HEADER = 12  # "RIFF", size, "WEBP"


class WebpStructureError(ValueError):
    """The RIFF container is truncated, mis-sized or not a WebP."""


def _chunks(data: bytes):
    """``(type, chunk bytes including padding)`` for each chunk, checked."""
    if len(data) < _HEADER or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise WebpStructureError("not a RIFF WebP")
    (riff_size,) = struct.unpack("<I", data[4:8])
    end = 8 + riff_size
    if riff_size & 1 or end > len(data):
        raise WebpStructureError("RIFF size does not match the file")
    offset = _HEADER
    while offset < end:
        if offset + 8 > end:
            raise WebpStructureError("truncated chunk header")
        kind = data[offset : offset + 4]
        (length,) = struct.unpack("<I", data[offset + 4 : offset + 8])
        stop = offset + 8 + length + (length & 1)
        if stop > end:
            raise WebpStructureError(f"truncated {kind!r} chunk")
        yield kind, data[offset:stop]
        offset = stop


def is_lossless(data: bytes) -> bool:
    """Whether the WebP's (first) image chunk is ``VP8L``."""
    for kind, _ in _chunks(data):
        if kind in (b"VP8 ", b"VP8L"):
            return kind == b"VP8L"
    return False


def strip_chunks(data: bytes) -> bytes | None:
    """*data* without its metadata chunks, or ``None`` when there were none.

    Whatever follows the RIFF size is dropped too, as a PNG's tail after
    ``IEND`` is: it is not part of the image.
    """
    kept: list[bytes] = []
    dropped = False
    for kind, chunk in _chunks(data):
        if kind not in KEPT:
            dropped = True
        elif kind == b"VP8X":
            if len(chunk) < 18:
                raise WebpStructureError("truncated VP8X chunk")
            flags = chunk[8] & ~(_EXIF_FLAG | _XMP_FLAG)
            dropped = dropped or flags != chunk[8]
            kept.append(chunk[:8] + bytes([flags]) + chunk[9:])
        else:
            kept.append(chunk)
    if not {chunk[:4] for chunk in kept} & {b"VP8 ", b"VP8L", b"ANMF"}:
        raise WebpStructureError("no image chunk")
    body = b"".join(kept)
    if not dropped and _HEADER + len(body) == len(data):
        return None
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body
