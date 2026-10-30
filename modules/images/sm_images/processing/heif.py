"""HEIC/HEIF support for Pillow, registered explicitly and once.

Every module that opens image bytes (the sniffer, the EXIF reader, the
rendition encoder) calls :func:`register_heif` itself, so none of them depends
on another being imported first for its side effect.
"""

from __future__ import annotations

import threading

import pillow_heif

__all__ = ["register_heif"]

_registered = False
_lock = threading.Lock()


def register_heif() -> None:
    """Register ``pillow-heif``'s opener with Pillow. Idempotent and thread-safe."""
    global _registered
    if _registered:
        return
    with _lock:
        if not _registered:
            pillow_heif.register_heif_opener()
            _registered = True
