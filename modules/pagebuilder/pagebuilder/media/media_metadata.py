"""Removing camera metadata from an uploaded original (#356).

A photo from a phone carries EXIF (GPS coordinates, device and serial number,
capture time, sometimes the owner's name), XMP and IPTC, and the media library
publishes the original as uploaded. :func:`strip_metadata` re-saves a JPEG, PNG
or WebP without any of it, behind the ``media_strip_metadata`` setting.

What is kept: the pixels, upright (EXIF orientation is applied first, since the
tag that said how to turn them is going), the ICC colour profile, and a
palette image's transparency. What is left alone entirely: animated images, a
file Pillow cannot read, and one above the pixel limit, which
:func:`~pagebuilder.media.media_images.process_image` then refuses.
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from pagebuilder.media.media_images import is_animated

logger = logging.getLogger(__name__)

_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
# Kept from ``Image.info``; everything else there (exif, xmp, comment, text
# chunks, Photoshop/IPTC resources) is what this exists to drop.
_KEPT_INFO = ("transparency",)
# A lossy WebP, or a JPEG Pillow cannot re-encode with its own tables.
_FALLBACK_QUALITY = 92


def _webp_is_lossless(source: Path) -> bool:
    """Whether the WebP's image chunk is ``VP8L``, walking the RIFF chunks."""
    data = source.read_bytes()
    offset = 12
    while offset + 8 <= len(data):
        tag = data[offset : offset + 4]
        (length,) = struct.unpack("<I", data[offset + 4 : offset + 8])
        if tag in (b"VP8 ", b"VP8L"):
            return tag == b"VP8L"
        offset += 8 + length + (length & 1)
    return False


def _save_options(image: Image.Image, fmt: str, source: Path) -> dict[str, Any]:
    options: dict[str, Any] = {"format": fmt}
    if icc := image.info.get("icc_profile"):
        options["icc_profile"] = icc
    if fmt == "JPEG":
        # The original's own quantisation tables: no second round of loss
        # beyond the re-encode itself, and no file growing for nothing.
        options.update(quality="keep", subsampling="keep")
    elif fmt == "WEBP":
        if _webp_is_lossless(source):
            options["lossless"] = True
        else:
            options["quality"] = _FALLBACK_QUALITY
    return options


def _exceeds_pixel_limit(image: Image.Image) -> bool:
    limit = Image.MAX_IMAGE_PIXELS
    return limit is not None and image.size[0] * image.size[1] > limit


def strip_metadata(source: Path, content_type: str) -> bool:
    """Re-save *source* in place without its metadata; ``True`` if it was rewritten.

    ``False`` — the file untouched — for a type this does not handle, an
    animated image, a file Pillow cannot read and one above the pixel limit
    (never decoded here; the caller's own check refuses it).
    """
    fmt = _FORMATS.get(content_type)
    if fmt is None:
        return False
    scratch = source.with_name(f"{source.name}.strip")
    try:
        with Image.open(source) as image:
            if _exceeds_pixel_limit(image) or is_animated(image):
                return False
            options = _save_options(image, fmt, source)
            image.load()
            # In place, so a JPEG stays a JPEG image and "keep" can read its tables.
            ImageOps.exif_transpose(image, in_place=True)
            image.info = {key: image.info[key] for key in _KEPT_INFO if key in image.info}
            try:
                image.save(scratch, **options)
            except ValueError:
                if fmt != "JPEG":
                    raise
                options.update(quality=_FALLBACK_QUALITY, subsampling=-1)
                image.save(scratch, **options)
        scratch.replace(source)
    except (UnidentifiedImageError, OSError, ValueError, struct.error, IndexError,
            Image.DecompressionBombError) as exc:
        logger.warning("Kept metadata on %s: it could not be re-saved (%s)", source.name, exc)
        return False
    finally:
        scratch.unlink(missing_ok=True)  # gone already once it replaced the source
    return True
