"""What an upload's stored original goes through before its row is written.

Split out of :mod:`pagebuilder.media.media_service` (file-size cap): removing
its metadata (#356), then reading its size and cutting its thumbnails, and
turning each refusal into the HTTP answer the console understands. Whatever
goes wrong, the original is removed: no file is left behind without a row.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from pagebuilder.core.settings import PagebuilderSettings
from pagebuilder.media.media_gif import AmbiguousGifError
from pagebuilder.media.media_images import TooManyPixelsError, process_image
from pagebuilder.media.media_metadata import MetadataNotRemovedError, strip_metadata


async def process_stored(
    target: Path, content_type: str, size: int, settings: PagebuilderSettings
) -> tuple[int, int | None, int | None, dict[str, Any]]:
    """``(size_bytes, width, height, variants)`` for the file at *target*.

    ``size_bytes`` is *size* unless the file was re-saved without its metadata.
    """
    # Pillow's decode + webp encode are sync and CPU-bound — running
    # them on the event loop blocks other concurrent uploads. The
    # thread offload is essentially free for a single request and
    # turns parallel uploads back into parallel work.
    try:
        # Before the thumbnails, so they are cut from the upright, clean file (#356).
        if settings.media_strip_metadata and await asyncio.to_thread(
            strip_metadata, target, content_type
        ):
            size = target.stat().st_size
        width, height, variants = await asyncio.to_thread(
            process_image,
            target,
            thumbnail_widths=settings.media_thumbnail_widths,
            webp_quality=settings.media_webp_quality,
        )
    except TooManyPixelsError:
        # Raised before any thumbnail is written, so the original is the
        # only file to remove. The code lets the console say "too many
        # pixels" rather than the byte-size sentence a plain 413 gets.
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail={
                "code": "image_too_many_pixels",
                "message": "Image dimensions exceed the pixel limit",
            },
        ) from None
    except MetadataNotRemovedError:
        # Fails closed (#356): never published with its GPS position.
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=415,
            detail={"code": "image_metadata_not_removed",
                    "message": "The image's metadata could not be removed"},
        ) from None
    except AmbiguousGifError:
        # A GIF whose frames cannot be counted the way Pillow counts them
        # is refused like any file that is not a valid image.
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=415, detail="GIF structure could not be verified"
        ) from None
    except BaseException:
        # Anything unexpected must not leave an unlisted file behind.
        target.unlink(missing_ok=True)
        raise
    return size, width, height, variants
