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

# Where a kept chunk goes (PNG spec, chunk ordering): before PLTE and IDAT, or
# after PLTE and before IDAT.
_BEFORE_PLTE = frozenset(
    {b"cHRM", b"gAMA", b"iCCP", b"sBIT", b"sRGB", b"cICP", b"mDCV", b"cLLI", b"pHYs", b"sPLT"}
)
_AFTER_PLTE = frozenset({b"tRNS", b"bKGD", b"hIST"})
# Values on the scale of the IHDR bit depth and colour type: carried only when
# Pillow wrote the same ones (a 4-bit grey PNG comes back 8-bit).
_SAMPLE_SCALED = frozenset({b"tRNS", b"bKGD", b"sBIT", b"hIST"})
_CARRIED = _BEFORE_PLTE | _AFTER_PLTE
# APNG frame control and data: an animated PNG is cleaned by copying them as
# they are (no orientation is applied to one).
KEPT_ANCILLARY = _CARRIED | {b"acTL", b"fcTL", b"fdAT"}


class PngStructureError(ValueError):
    """The chunk stream is truncated or not a PNG."""


def _kept(kind: bytes) -> bool:
    return kind[:1].isupper() or kind in KEPT_ANCILLARY


def _chunks(data: bytes):
    """``(type, chunk)`` up to ``IEND``; a kept chunk with a bad CRC is refused.

    A chunk that is dropped anyway is not checked: leaving it out cleans the
    file whatever it holds, and the cleaned bytes are decoded whole after.
    """
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
        if _kept(kind) and zlib.crc32(data[offset + 4 : end - 4]) != crc:
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
        if _kept(kind):
            kept.append(chunk)
            total += len(chunk)
        else:
            dropped = True
    if not dropped and total == len(data):
        return None
    return b"".join(kept)


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def _swapped_phys(chunk: bytes) -> bytes:
    """``pHYs`` with its x and y pixel densities exchanged, for a quarter turn."""
    x, y, unit = struct.unpack(">IIB", chunk[8:17])
    return _chunk(b"pHYs", struct.pack(">IIB", y, x, unit))


def _format(chunks: list[tuple[bytes, bytes]]) -> bytes:
    """IHDR's bit depth and colour type bytes."""
    kind, chunk = chunks[0]
    if kind != b"IHDR":
        raise PngStructureError("IHDR is not the first chunk")
    return chunk[16:18]


def carry_chunks(original: bytes, rendered: bytes, *, swap_axes: bool) -> bytes:
    """*rendered* (a PNG Pillow wrote) with *original*'s kept ancillary chunks.

    Pillow keeps only the ICC profile and transparency of what it was given, so
    a re-saved PNG would lose its gamma, chromaticities, sRGB intent and the
    rest. Every carried chunk of *original* replaces the rendered file's chunks
    of that type, every instance in its original order (``sPLT`` may repeat),
    placed where the spec requires; ``tRNS`` is the rendered one when Pillow
    wrote it. When Pillow changed the bit depth or colour type, ``bKGD``,
    ``sBIT``, ``hIST`` and the original ``tRNS`` are left out: their values
    are on the old scale. *swap_axes* is a quarter turn: ``pHYs``' densities
    are exchanged with the dimensions.
    """
    out = list(_chunks(rendered))
    source = list(_chunks(original))
    rendered_trns = any(kind == b"tRNS" for kind, _ in out)
    same_format = _format(source) == _format(out)
    carried = [
        (kind, _swapped_phys(chunk) if swap_axes and kind == b"pHYs" else chunk)
        for kind, chunk in source
        if kind in _CARRIED
        and not (kind == b"tRNS" and rendered_trns)
        and (same_format or kind not in _SAMPLE_SCALED)
    ]
    replaced = {kind for kind, _ in carried}
    before = [chunk for kind, chunk in carried if kind in _BEFORE_PLTE]
    after = [chunk for kind, chunk in carried if kind in _AFTER_PLTE]
    result = [PNG_SIGNATURE]
    for kind, chunk in out:
        if kind in replaced:
            continue
        if kind in (b"PLTE", b"IDAT") and before:
            result += before
            before = []
        if kind == b"IDAT" and after:
            result += after
            after = []
        result.append(chunk)
        if kind == b"PLTE":
            result += after
            after = []
    return b"".join(result)
