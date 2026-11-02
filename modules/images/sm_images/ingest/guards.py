"""Refusals every ingest path applies, before a byte is stored.

* :func:`guard_pixels` - the decompression-bomb guard, pagebuilder #221's
  behaviour: above twice ``Image.MAX_IMAGE_PIXELS`` Pillow raises
  ``DecompressionBombError``; between one and two times it only warns and would
  go on to decode the whole bitmap, so the same limit is applied to the header
  size and both are refused alike with a 413 ``image_too_many_pixels``.
  ``MAX_IMAGE_PIXELS = None`` (a host's choice) switches the guard off.
* :func:`inspect` - size cap, magic-byte sniff, pixel guard and a structural
  ``verify()``; the one call a path needs.
* :func:`read_bounded` - an ``UploadFile`` read in chunks that stops at the cap.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from typing import Any

from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from sm_images.core import constants
from sm_images.core.errors import FileTooLarge, ImageTooLarge, UnsupportedType
from sm_images.ingest.sniff import EXTENSIONS, sniff

__all__ = ["Inspected", "guard_pixels", "inspect", "read_bounded"]

_NOT_AN_IMAGE = "The file is not a supported image (JPEG, PNG, WebP, HEIC/HEIF or TIFF)"
_UNREADABLE = "The image could not be read"
_TOO_MANY_PIXELS = "Image dimensions exceed the pixel limit"
_TOO_LARGE = "The file is larger than the image size limit"


@dataclass(frozen=True)
class Inspected:
    content_type: str
    ext: str
    width: int
    height: int


def _exceeds(width: int, height: int) -> bool:
    # Read at call time: a host (or a test) may lower it, or set it to None.
    limit = PILImage.MAX_IMAGE_PIXELS
    return limit is not None and width * height > limit


def guard_pixels(data: bytes) -> tuple[int, int]:
    """``(width, height)`` from the header; :class:`ImageTooLarge` above the limit,
    :class:`UnsupportedType` when Pillow cannot read the image structurally."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", PILImage.DecompressionBombWarning)
            with PILImage.open(io.BytesIO(data)) as img:
                width, height = img.size
                if _exceeds(width, height):
                    raise ImageTooLarge(_TOO_MANY_PIXELS)
                img.verify()
    except PILImage.DecompressionBombError as exc:
        raise ImageTooLarge(_TOO_MANY_PIXELS) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise UnsupportedType(_UNREADABLE) from exc
    if width <= 0 or height <= 0:
        raise UnsupportedType(_UNREADABLE)
    return width, height


def check_size(size: int, *, max_bytes: int) -> None:
    if size > max_bytes:
        raise FileTooLarge(_TOO_LARGE)


def inspect(data: bytes, *, max_bytes: int) -> Inspected:
    """Everything an original must pass, cheapest first."""
    check_size(len(data), max_bytes=max_bytes)
    content_type = sniff(data)
    if content_type is None:
        raise UnsupportedType(_NOT_AN_IMAGE)
    width, height = guard_pixels(data)
    return Inspected(content_type, EXTENSIONS[content_type], width, height)


async def read_staged(store: Any, key: str, max_bytes: int) -> bytes:
    """A staged object, capped by its stored size before it is loaded; a
    missing one (``head`` is ``None``) fails in ``read`` as it always did."""
    head = await store.head(key)
    if head is not None:
        check_size(head[0], max_bytes=max_bytes)
    return await store.read(key)


async def read_bounded(file: Any, limit: int, *, over: type[Exception] = FileTooLarge) -> bytes:
    """Read ``file`` (an ``UploadFile``) but never more than ``limit`` bytes;
    ``over`` is raised as soon as it would pass, before the rest is read."""
    if file.size is not None and file.size > limit:
        raise over(_TOO_LARGE)
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(constants.READ_CHUNK_BYTES):
        total += len(chunk)
        if total > limit:
            raise over(_TOO_LARGE)
        chunks.append(chunk)
    return b"".join(chunks)
