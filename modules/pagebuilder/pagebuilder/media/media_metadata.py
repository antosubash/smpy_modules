"""Removing camera metadata from an uploaded original (#356).

A photo from a phone carries EXIF (GPS coordinates, device and serial number,
capture time, sometimes the owner's name), XMP and IPTC, and the media library
publishes the original as uploaded. :func:`strip_metadata` re-saves a JPEG
without any of it, and copies a PNG's or WebP's chunks without its metadata
chunks (:mod:`~pagebuilder.media.media_png`, :mod:`~pagebuilder.media.media_webp`:
lossless, the compressed picture copied byte for byte), behind the
``media_strip_metadata`` setting. :func:`clean_bytes` is the same in memory,
which is how a bundle's media is matched by the digest it would be stored with.

An EXIF orientation other than 1 is applied by re-encoding: a JPEG, a static
WebP (lossless stays lossless, lossy is re-encoded at quality 92) and an 8-bit
PNG, which Pillow re-saves losslessly. A 16-bit PNG keeps its pixels as stored
and loses the tag: no re-encode would keep its depth. An animated PNG or WebP
is never re-encoded: its chunks are copied and an orientation tag just goes.

What is kept: the pixels, upright (EXIF orientation is applied first, since the
tag that said how to turn them is going), the ICC colour profile, and a
palette image's transparency. What is left alone entirely: GIF, and a file
with nothing to remove. It fails closed: a file it should
clean but cannot is refused, never stored with its metadata.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from pagebuilder.media import media_png, media_webp
from pagebuilder.media.media_images import (
    TooManyPixelsError,
    _exceeds_pixel_limit,
    is_animated,
)

_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
# Kept from ``Image.info``; everything else there (exif, xmp, comment, text
# chunks, Photoshop/IPTC resources) is what this exists to drop.
_KEPT_INFO = ("transparency",)
# A lossy WebP, or a JPEG Pillow cannot re-encode with its own tables.
_FALLBACK_QUALITY = 92
_EXIF_ORIENTATION = 0x0112


def _save_options(image: Image.Image, fmt: str, source: bytes) -> dict[str, Any]:
    options: dict[str, Any] = {"format": fmt}
    if icc := image.info.get("icc_profile"):
        options["icc_profile"] = icc
    if fmt == "JPEG":
        # The original's own quantisation tables: no second round of loss
        # beyond the re-encode itself, and no file growing for nothing.
        options.update(quality="keep", subsampling="keep")
        # Not metadata: how the picture is meant to be sized and streamed. The
        # caller drops ``Image.info``, which is where Pillow reads both from.
        if dpi := image.info.get("dpi"):
            options["dpi"] = dpi
        if image.info.get("progressive") or image.info.get("progression"):
            options["progressive"] = True
    elif fmt == "WEBP":
        if media_webp.is_lossless(source):
            options["lossless"] = True
        else:
            options["quality"] = _FALLBACK_QUALITY
    return options


class MetadataNotRemovedError(Exception):
    """A JPEG, PNG or WebP whose metadata could not be removed; the upload is refused.

    Fails closed: with ``media_strip_metadata`` on, an original is either
    cleaned or not stored, never published with its GPS position by accident.
    """


# JPEG APP segments that are not metadata: JFIF (APP0), ICC (APP2), Adobe (APP14).
_JPEG_HARMLESS_APP = {"APP0", "APP2", "APP14"}
_INFO_METADATA = ("exif", "xmp", "XML:com.adobe.xmp", "comment", "photoshop")


def _has_metadata(image: Image.Image) -> bool:
    """Whether there is anything to remove: a clean file is left byte for byte.

    That keeps the step idempotent — a restored bundle's already-clean JPEG is
    not re-encoded, so its digest still matches on the next restore.
    """
    if len(image.getexif()) or any(key in image.info for key in _INFO_METADATA):
        return True
    if image.format == "MPO":
        return True  # its other pictures go too
    if image.format == "JPEG" and any(m not in _JPEG_HARMLESS_APP for m, _ in image.applist):
        return True
    return bool(getattr(image, "text", None))  # PNG tEXt/iTXt/zTXt chunks


def _turns(image: Image.Image) -> bool:
    return image.getexif().get(_EXIF_ORIENTATION, 1) != 1


def _png_turns(image: Image.Image, data: bytes) -> bool:
    """Whether an 8-bit PNG carries an orientation to apply by re-saving it."""
    return _turns(image) and media_png.bit_depth(data) <= 8


# Lossless cleaning by copying the container's chunks without the metadata ones.
_CHUNK_COPY = {"PNG": media_png.strip_chunks, "WEBP": media_webp.strip_chunks}


def _verified(cleaned: bytes | None) -> bytes | None:
    """*cleaned*, once Pillow has decoded it whole: never store an unreadable original."""
    if cleaned is not None:
        with Image.open(io.BytesIO(cleaned)) as image:
            image.load()
    return cleaned


def clean_bytes(data: bytes, content_type: str) -> bytes | None:
    """*data* without its metadata, or ``None`` when it is to be stored as it is.

    ``None`` for a type this does not handle and a file with no metadata to
    remove. A WebP, and an animated PNG, has its chunks copied without the
    metadata ones, unless an orientation must be applied to a static WebP. A
    multi-picture JPEG (MPO, how many phones save a photo) is not animated:
    its primary picture is kept, as a plain JPEG, and the rest dropped.

    Raises :class:`~pagebuilder.media.media_images.TooManyPixelsError` above the
    pixel limit, before decoding anything, and :class:`MetadataNotRemovedError`
    when the file cannot be read or re-saved.
    """
    fmt = _FORMATS.get(content_type)
    if fmt is None:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            if _exceeds_pixel_limit(*image.size):
                raise TooManyPixelsError(f"{image.size} exceeds Image.MAX_IMAGE_PIXELS")
            if image.format == "MPO":
                image.seek(0)
            elif is_animated(image) or (fmt == "WEBP" and not _turns(image)):
                # An animated file keeps its frames as they are, turned or not.
                strip = _CHUNK_COPY.get(fmt)
                return _verified(strip(data)) if strip else None
            if fmt == "PNG" and not _png_turns(image, data):
                image.load()  # fail closed on a PNG whose pixels do not decode
                return _verified(media_png.strip_chunks(data))
            if not _has_metadata(image):
                return None
            options = _save_options(image, fmt, data)
            quarter_turn = image.getexif().get(_EXIF_ORIENTATION, 1) in (5, 6, 7, 8)
            image.load()
            # In place, so a JPEG stays a JPEG image and "keep" can read its tables.
            ImageOps.exif_transpose(image, in_place=True)
            image.info = {key: image.info[key] for key in _KEPT_INFO if key in image.info}
            out = io.BytesIO()
            try:
                image.save(out, **options)
            except ValueError:
                if fmt != "JPEG":
                    raise
                options.update(quality=_FALLBACK_QUALITY, subsampling=-1)
                out = io.BytesIO()
                image.save(out, **options)
            if fmt == "PNG":
                # Pillow kept only ICC and transparency: put the gamma,
                # chromaticities, sRGB intent and the rest back.
                return _verified(
                    media_png.carry_chunks(data, out.getvalue(), swap_axes=quarter_turn)
                )
            return _verified(out.getvalue())
    except Image.DecompressionBombError as exc:
        raise TooManyPixelsError(str(exc)) from exc
    # Pillow reports some broken PNG chunks as ``SyntaxError``.
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, struct.error,
            IndexError) as exc:
        raise MetadataNotRemovedError(str(exc)) from exc


def strip_metadata(source: Path, content_type: str) -> bool:
    """:func:`clean_bytes` on the file at *source*, in place; ``True`` if rewritten.

    Both refusals are the caller's to turn into an answer; the file is untouched.
    """
    if content_type not in _FORMATS:
        return False  # a GIF, SVG, PDF…: not worth reading into memory to say so
    cleaned = clean_bytes(source.read_bytes(), content_type)
    if cleaned is None:
        return False
    scratch = source.with_name(f"{source.name}.strip")
    try:
        scratch.write_bytes(cleaned)
        scratch.replace(source)
    finally:
        scratch.unlink(missing_ok=True)  # gone already once it replaced the source
    return True
