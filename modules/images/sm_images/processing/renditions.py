"""Rendition encoding as a pure function (bytes in, JPEG bytes out).

Ported from the portal's ``pipeline/thumbnails.py``: white composite for
transparent or palette input, RGB conversion, EXIF transpose, LANCZOS
aspect-fit, JPEG q85, never enlarging. Unlike the portal, nothing is swallowed
per size: any failure raises and there is no partial result, so the step is
either complete for every requested size or failed and retryable.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import Final

from PIL import Image, ImageOps

from sm_images.processing.heif import register_heif

register_heif()

__all__ = ["make_renditions"]

_QUALITY: Final = 85


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode == "P" or "transparency" in img.info or img.mode in ("RGBA", "LA", "PA"):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB") if img.mode != "RGB" else img


def make_renditions(
    display_bytes: bytes, sizes: Mapping[str, int]
) -> dict[str, tuple[bytes, int, int]]:
    """``{name: (jpeg_bytes, width, height)}`` for every name in ``sizes``.

    ``sizes`` maps a name to the longest edge in pixels. A source smaller than
    a size is not enlarged: that name gets the source's (oriented) dimensions.
    Metadata is stripped. Raises on an undecodable input or a non-positive size.
    """
    for name, edge in sizes.items():
        if edge <= 0:
            raise ValueError(f"rendition {name!r}: size must be positive, got {edge}")
    with Image.open(io.BytesIO(display_bytes)) as src:
        src.load()
        oriented = _to_rgb(ImageOps.exif_transpose(src))
    out: dict[str, tuple[bytes, int, int]] = {}
    for name, edge in sizes.items():
        img = oriented.copy()
        img.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_QUALITY, optimize=True)
        out[name] = (buf.getvalue(), img.width, img.height)
    return out
