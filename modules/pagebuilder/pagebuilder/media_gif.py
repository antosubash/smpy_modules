"""The canvas a GIF actually needs, read from its block headers alone.

``Image.open`` reports a GIF's logical screen, but a frame's image descriptor
may place it partly or wholly outside that screen, and Pillow grows the
canvas to cover it when it reaches the frame. So a GIF whose first frame is
small can still be a decompression bomb from its second frame on (#221).

Walking the block structure finds every frame's extent without decoding any
pixel data: each data sub-block is skipped by its length byte. APNG and
animated WebP need no such walk: their frames must lie inside the canvas,
which Pillow and libwebp enforce, so the canvas size already bounds them.

The walk follows Pillow's reader (``GifImageFile._seek``) rather than the
spec, so the two cannot disagree about which frames exist: a byte that
introduces no block is skipped, not treated as the end, and only the ``;``
trailer or the end of the file stops it. A frame counts as soon as its
descriptor is read, which is also when Pillow checks its size.
"""

from __future__ import annotations

import re
from pathlib import Path

# The next block introducer: extension, image descriptor, or trailer. Pillow
# steps over any other byte one at a time; searching for the next one is the
# same walk without a Python-level loop per byte of junk.
_INTRODUCER = re.compile(rb"[!,;]")


def _u16(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos : pos + 2], "little")


def _color_table_size(flags: int) -> int:
    return 3 << ((flags & 7) + 1) if flags & 0x80 else 0


def _skip_sub_blocks(data: bytes, pos: int) -> int:
    """Position after a chain of length-prefixed sub-blocks (or past the end)."""
    while pos < len(data) and data[pos]:
        pos += 1 + data[pos]
    return pos + 1


def gif_canvas_size(source: Path) -> tuple[int, int] | None:
    """The logical screen grown to cover every frame, or ``None`` if not a GIF.

    Reads the whole file: uploads are already capped by ``media_max_bytes``.
    """
    data = source.read_bytes()
    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width, height = _u16(data, 6), _u16(data, 8)
    pos = 13 + _color_table_size(data[10])
    while (match := _INTRODUCER.search(data, pos)) is not None:
        pos = match.start() + 1
        introducer = match.group()
        if introducer == b";":
            break
        if introducer == b"!":  # extension: one label byte, then sub-blocks
            pos = _skip_sub_blocks(data, pos + 1)
            continue
        if pos + 9 > len(data):  # truncated image descriptor: no frame
            break
        x0, y0, w, h = (_u16(data, pos + i) for i in range(0, 8, 2))
        width, height = max(width, x0 + w), max(height, y0 + h)
        # Local colour table, then the LZW code size byte, then the data.
        pos += 9 + _color_table_size(data[pos + 8]) + 1
        pos = _skip_sub_blocks(data, pos)
    return width, height
