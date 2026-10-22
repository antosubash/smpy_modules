"""The canvas a GIF actually needs, read from its block headers alone.

``Image.open`` reports a GIF's logical screen, but a frame's image descriptor
may place it partly or wholly outside that screen, and Pillow grows the
canvas to cover it when it reaches the frame. So a GIF whose first frame is
small can still be a decompression bomb from its second frame on (#221).

Walking the block structure finds every frame's extent without decoding any
pixel data: each data sub-block is skipped by its length byte. APNG and
animated WebP need no such walk: their frames must lie inside the canvas,
which Pillow and libwebp enforce, so the canvas size already bounds them.
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO


def _skip_sub_blocks(fh: BinaryIO) -> bool:
    """Skip a chain of length-prefixed sub-blocks; ``False`` if truncated."""
    while True:
        size = fh.read(1)
        if not size:
            return False
        if size[0] == 0:
            return True
        fh.seek(size[0], 1)


def _color_table_size(flags: int) -> int:
    return 3 << ((flags & 7) + 1) if flags & 0x80 else 0


def gif_canvas_size(source: Path) -> tuple[int, int] | None:
    """The logical screen grown to cover every frame, or ``None`` if not a GIF.

    A truncated or malformed file stops the walk and returns what was seen so
    far; deciding whether the file decodes at all is Pillow's job.
    """
    with source.open("rb") as fh:
        header = fh.read(13)
        if len(header) < 13 or header[:6] not in (b"GIF87a", b"GIF89a"):
            return None
        width = int.from_bytes(header[6:8], "little")
        height = int.from_bytes(header[8:10], "little")
        fh.seek(_color_table_size(header[10]), 1)
        while True:
            introducer = fh.read(1)
            if introducer == b"!":  # extension: label, then sub-blocks
                if not fh.read(1) or not _skip_sub_blocks(fh):
                    break
            elif introducer == b",":  # image descriptor
                desc = fh.read(9)
                if len(desc) < 9:
                    break
                x0, y0, w, h = (int.from_bytes(desc[i : i + 2], "little") for i in range(0, 8, 2))
                width, height = max(width, x0 + w), max(height, y0 + h)
                fh.seek(_color_table_size(desc[8]), 1)
                if not fh.read(1) or not _skip_sub_blocks(fh):  # LZW code size
                    break
            else:  # trailer, EOF, or garbage
                break
    return width, height
