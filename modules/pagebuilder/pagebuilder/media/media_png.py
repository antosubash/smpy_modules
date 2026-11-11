"""Removing a PNG's metadata at the chunk level, without re-encoding it (#356).

Re-saving through Pillow drops a 16-bit-per-channel PNG to 8 bits, so a PNG is
cleaned by copying its chunk stream and leaving out the ancillary chunks that
are not about how to draw the picture. That is lossless for every bit depth
and colour type: ``IDAT`` is copied byte for byte.

Kept: every critical chunk (``IHDR``, ``PLTE``, ``IDAT``, ``IEND`` and any
other whose type starts upper-case, which a decoder must understand) and the
ancillary chunks listed in :data:`KEPT_ANCILLARY` (colour, transparency,
physical size). Dropped: every other ancillary chunk — ``tEXt``, ``zTXt``,
``iTXt``, ``eXIf``, ``tIME`` and anything private, such as an embedded
provenance manifest.
"""

from __future__ import annotations

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

KEPT_ANCILLARY = frozenset(
    {
        b"tRNS", b"cHRM", b"gAMA", b"iCCP", b"sBIT", b"sRGB", b"cICP", b"mDCV",
        b"cLLI", b"bKGD", b"hIST", b"pHYs", b"sPLT",
        # APNG. An animated PNG never reaches here, but its chunks are pixels.
        b"acTL", b"fcTL", b"fdAT",
    }
)


class PngStructureError(ValueError):
    """The chunk stream is truncated or not a PNG."""


def _chunks(data: bytes):
    if not data.startswith(PNG_SIGNATURE):
        raise PngStructureError("not a PNG")
    offset = len(PNG_SIGNATURE)
    while offset < len(data):
        if offset + 8 > len(data):
            raise PngStructureError("truncated chunk header")
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise PngStructureError(f"truncated {kind!r} chunk")
        (crc,) = struct.unpack(">I", data[end - 4 : end])
        if zlib.crc32(data[offset + 4 : end - 4]) != crc:
            raise PngStructureError(f"bad CRC in {kind!r} chunk")
        yield kind, data[offset:end]
        offset = end
        if kind == b"IEND":
            return
    raise PngStructureError("no IEND chunk")


def bit_depth(data: bytes) -> int:
    """The IHDR bit depth (1, 2, 4, 8 or 16)."""
    for kind, chunk in _chunks(data):
        if kind == b"IHDR":
            return chunk[16]  # length, type, width, height, then the depth byte
        break
    raise PngStructureError("IHDR is not the first chunk")


def strip_chunks(data: bytes) -> bytes | None:
    """*data* without its metadata chunks, or ``None`` when there were none.

    Whatever follows ``IEND`` is dropped too: it is not part of the image, and
    is a place to hide a payload.
    """
    kept: list[bytes] = [PNG_SIGNATURE]
    dropped = False
    total = len(PNG_SIGNATURE)
    for kind, chunk in _chunks(data):
        critical = kind[:1].isupper()
        if critical or kind in KEPT_ANCILLARY:
            kept.append(chunk)
            total += len(chunk)
        else:
            dropped = True
    if not dropped and total == len(data):
        return None
    return b"".join(kept)


# Where a carried chunk goes (PNG spec, chunk ordering): before PLTE and IDAT,
# or after PLTE and before IDAT.
_BEFORE_PLTE = frozenset(
    {b"cHRM", b"gAMA", b"iCCP", b"sBIT", b"sRGB", b"cICP", b"mDCV", b"cLLI", b"pHYs", b"sPLT"}
)
_AFTER_PLTE = frozenset({b"tRNS", b"bKGD", b"hIST"})
_CARRIED = _BEFORE_PLTE | _AFTER_PLTE


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def _swapped_phys(chunk: bytes) -> bytes:
    """``pHYs`` with its x and y pixel densities exchanged, for a quarter turn."""
    x, y, unit = struct.unpack(">IIB", chunk[8:17])
    return _chunk(b"pHYs", struct.pack(">IIB", y, x, unit))


def carry_chunks(original: bytes, rendered: bytes, *, swap_axes: bool) -> bytes:
    """*rendered* (a PNG Pillow wrote) with *original*'s kept ancillary chunks.

    Pillow keeps only the ICC profile and transparency of what it was given, so
    a re-saved PNG would lose its gamma, chromaticities, sRGB intent and the
    rest. Every :data:`KEPT_ANCILLARY` chunk of *original* replaces the
    rendered file's chunk of the same type, placed where the spec requires;
    ``tRNS`` is the rendered one when Pillow wrote it. *swap_axes* is a quarter
    turn: ``pHYs``' densities are exchanged with the dimensions.
    """
    carried = {
        kind: chunk
        for kind, chunk in _chunks(original)
        if kind in _CARRIED
    }
    if swap_axes and b"pHYs" in carried:
        carried[b"pHYs"] = _swapped_phys(carried[b"pHYs"])
    out = list(_chunks(rendered))
    if any(kind == b"tRNS" for kind, _ in out):
        carried.pop(b"tRNS", None)
    out = [(kind, chunk) for kind, chunk in out if kind not in carried]
    before = [chunk for kind, chunk in carried.items() if kind in _BEFORE_PLTE]
    after = [chunk for kind, chunk in carried.items() if kind in _AFTER_PLTE]
    result = [PNG_SIGNATURE]
    for kind, chunk in out:
        if kind == b"IDAT" and before is not None:
            result += before + after
            before = after = None  # type: ignore[assignment]
        elif kind == b"PLTE" and before is not None:
            result += before
            before = []
        result.append(chunk)
        if kind == b"PLTE":
            result += after
            after = []
    return b"".join(result)
