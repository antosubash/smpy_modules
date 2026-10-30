"""Padding and blurring the detected regions. Pillow only, no heavy imports.

A region is first pixelated (averaged into coarse blocks, which no deblurring
recovers) and then Gaussian-blurred so the blocks do not read as a mosaic.
Ported from the portal's ``_pad_and_clamp_box``, except that the padded box is
clamped edge by edge: a box cut by the image border keeps its far edge rather
than growing past it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageFilter

__all__ = ["Region", "blur_regions", "pad_and_clamp"]

_BLOCKS = 8
"""A region's shorter side is averaged into about this many blocks."""


@dataclass(frozen=True, slots=True)
class Region:
    kind: str
    x: int
    y: int
    w: int
    h: int
    score: float

    def as_output(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "score": round(self.score, 4),
        }


def pad_and_clamp(
    x: float, y: float, w: float, h: float, img_w: int, img_h: int, padding: float
) -> tuple[int, int, int, int]:
    """Grow a box by ``padding`` x its own size on every side, rounded outwards
    (more blur, never less), then clamped to the image. Returns ``(x, y, w, h)``."""
    pad_w, pad_h = w * padding, h * padding
    x0 = max(0, math.floor(x - pad_w))
    y0 = max(0, math.floor(y - pad_h))
    x1 = min(img_w, math.ceil(x + w + pad_w))
    y1 = min(img_h, math.ceil(y + h + pad_h))
    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)


def _obscure(patch: Image.Image) -> Image.Image:
    w, h = patch.size
    block = max(1, min(w, h) // _BLOCKS)
    small = patch.resize((max(1, w // block), max(1, h // block)), Image.Resampling.BOX)
    coarse = small.resize((w, h), Image.Resampling.NEAREST)
    return coarse.filter(ImageFilter.GaussianBlur(radius=max(1.0, float(block))))


def blur_regions(image: Image.Image, regions: list[Region]) -> Image.Image:
    """A copy of *image* with every region obscured."""
    out = image.copy()
    for r in regions:
        if r.w <= 0 or r.h <= 0:
            continue
        box = (r.x, r.y, r.x + r.w, r.y + r.h)
        out.paste(_obscure(out.crop(box)), box)
    return out
