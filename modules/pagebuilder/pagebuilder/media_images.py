"""Filename, content-sniffing, and image-processing helpers for uploads.

Extracted from :mod:`pagebuilder.media_service` so that module stays focused
on storage + DB operations. These are pure functions — they take everything
they need as arguments rather than reading service state — which also makes
them directly testable.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,8}$")

# Folders are user-supplied path-like strings, so we constrain the
# alphabet and reject traversal segments before they reach the DB.
_FOLDER_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_FOLDER_MAX_LENGTH = 300

# Header signatures for the formats this module accepts. We sniff the
# first bytes of every upload so a malicious client can't claim
# `image/png` while shipping HTML/JS/PHP that StaticFiles would later
# serve back under a same-origin URL. Pure-Python so no native dep.
SNIFF_BYTES = 64

_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

# WebP needs a two-part check (RIFF + WEBP at offset 8); handled inline.
CONTENT_TYPE_EXTENSIONS: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def normalize_folder(raw: str | None) -> str | None:
    """Canonicalize a folder path or raise 422.

    Strips surrounding slashes/whitespace, collapses double slashes,
    and validates each segment against ``_FOLDER_SEGMENT_RE``. An empty
    or ``None`` input becomes ``None`` (the asset is unfiled).
    """
    if raw is None:
        return None
    cleaned = raw.strip().strip("/")
    if not cleaned:
        return None
    if len(cleaned) > _FOLDER_MAX_LENGTH:
        raise HTTPException(status_code=422, detail="Folder path is too long")
    segments = [seg for seg in cleaned.split("/") if seg]
    for segment in segments:
        if segment in {".", ".."} or not _FOLDER_SEGMENT_RE.match(segment):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Folder segments must start with an alphanumeric and "
                    "contain only letters, digits, '.', '_' or '-'"
                ),
            )
    return "/".join(segments)


def sniff_content_type(head: bytes) -> str | None:
    for sig, ctype in _MAGIC_SIGNATURES:
        if head.startswith(sig):
            return ctype
    if len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def safe_extension(name: str) -> str:
    match = _EXT_RE.search(name or "")
    return match.group(0).lower() if match else ""


def is_animated(image: Image.Image) -> bool:
    """Detect multi-frame images we should leave alone.

    Pillow can downscale individual frames of animated GIF/WEBP but
    re-encoding the animation into webp is a different code path and
    the issue's acceptance criteria explicitly say animated GIFs skip
    transcoding. ``getattr`` defends against formats where Pillow
    doesn't set ``is_animated`` at all.
    """
    return bool(getattr(image, "is_animated", False))


def process_image(
    source: Path,
    *,
    thumbnail_widths: tuple[int, ...],
    webp_quality: int,
) -> tuple[int | None, int | None, dict[str, Any]]:
    """Extract dimensions and generate webp thumbnails for a raster image.

    Returns ``(width, height, variants)``. On any failure (corrupt
    file, format Pillow can't decode, animated image) returns
    ``(None, None, {})`` so the upload still completes — the original
    is served as-is and the Image block falls back to a plain
    ``<img src>``.
    """
    try:
        with Image.open(source) as image:
            src_w, src_h = image.size
            if src_w <= 0 or src_h <= 0:
                return src_w or None, src_h or None, {}
            # Capture dimensions even for animated images — the
            # original is still served, and a known intrinsic size
            # lets the Image block emit width/height to avoid CLS.
            if is_animated(image):
                return src_w, src_h, {}
            image.load()
            variants = generate_thumbnails(
                image,
                source,
                src_w,
                src_h,
                thumbnail_widths=thumbnail_widths,
                webp_quality=webp_quality,
            )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        # Logged at INFO because this is expected for corrupt or
        # exotic-but-valid uploads — not a code bug.
        logger.info("Skipping image processing for %s: %s", source.name, exc)
        return None, None, {}
    return src_w, src_h, variants


def generate_thumbnails(
    image: Image.Image,
    source: Path,
    src_w: int,
    src_h: int,
    *,
    thumbnail_widths: tuple[int, ...],
    webp_quality: int,
) -> dict[str, Any]:
    widths = sorted({w for w in thumbnail_widths if w > 0})
    if not widths:
        return {}
    # Webp doesn't support paletted/CMYK directly the same way; convert
    # once up front so each resize doesn't re-do the work.
    if image.mode not in ("RGB", "RGBA"):
        base = image.convert("RGBA" if "A" in image.mode else "RGB")
    else:
        base = image
    stem = source.stem
    out_dir = source.parent
    variants: dict[str, Any] = {}
    for width in widths:
        if width >= src_w:
            # No upscaling — skip widths at or above the source. The
            # original file already covers visitors at full size.
            continue
        ratio = width / src_w
        height = max(1, round(src_h * ratio))
        resized = base.resize((width, height), Image.Resampling.LANCZOS)
        out_name = f"{stem}_w{width}.webp"
        out_path = out_dir / out_name
        # method=4 is Google's recommended encoder default — method=6
        # is ~5x slower for marginal byte-size gains at q=82.
        resized.save(out_path, format="WEBP", quality=webp_quality, method=4)
        variants[f"w{width}"] = {
            "filename": out_name,
            "content_type": "image/webp",
            "width": width,
            "height": height,
            "size_bytes": out_path.stat().st_size,
        }
    return variants
