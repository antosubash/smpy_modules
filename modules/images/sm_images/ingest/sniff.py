"""What an upload *is*, from its magic bytes. The filename and the declared
content type are never trusted (portal ``upload_guards.sniff_image_content_type``).

It registers ``pillow-heif``'s opener (:func:`sm_images.processing.heif.register_heif`)
on import, so everything that sniffs can also open what it accepted (HEIC/HEIF).
"""

from __future__ import annotations

from typing import Final

from sm_images.processing.heif import register_heif

register_heif()

__all__ = ["EXTENSIONS", "sniff"]

_SNIFF_BYTES: Final = 32
_HEIC_BRANDS: Final = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis"})
_HEIF_BRANDS: Final = frozenset({b"mif1", b"msf1"})

EXTENSIONS: Final = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
    "image/tiff": "tif",
}
"""Every accepted type and the extension its original is stored under."""


def sniff(data: bytes) -> str | None:
    """The content type ``data`` actually is, or ``None`` if images does not take it."""
    head = data[:_SNIFF_BYTES]
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _HEIC_BRANDS:
            return "image/heic"
        if brand in _HEIF_BRANDS:
            return "image/heif"
    return None
