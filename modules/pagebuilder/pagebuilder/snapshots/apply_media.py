"""Restoring a bundle's media library, the first step of every apply.

Split from ``apply.py`` (300-line cap, #133): this step is the one that writes
files, and the one whose ``name_to_url`` every later step — pages, layout and
the contributed sections (#80) — resolves its ``asset://`` sentinels through.
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from pagebuilder.media_service import MediaService, media_file_names
from pagebuilder.models import MediaAsset
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.snapshots.blobs import BlobStore
from pagebuilder.snapshots.media_match import match_existing
from pagebuilder.snapshots.written import track


async def restore_media(
    db: AsyncSession,
    settings: PagebuilderSettings,
    blobs: BlobStore,
    index: dict[str, Any],
) -> tuple[dict[str, str], int]:
    """Ensure every bundled file exists here; return ``{bundle name: url}``.

    Matching against what is already here goes through ``match_existing``,
    which narrows by ``original_filename`` and then confirms by digest. Re-
    running a restore is still idempotent — same content, same match, no
    duplicate — but a host that happens to have a *different* picture under
    that name no longer has every page repointed at it silently.

    Within one bundle, though, the cache is keyed by digest, not by name.
    ``original_filename`` is a label two different uploads can share — which is
    exactly why ``bundle_names`` mints ``photo~2.jpg`` — so a name-keyed cache
    would make the second file resolve to the first one's asset and silently
    drop its bytes.

    Bytes go back through ``MediaService.upload`` rather than straight to disk,
    so thumbnails regenerate against this host's current settings and a bundle
    carrying a disallowed content-type is refused exactly as an upload would be.

    Every file an upload writes — the original and each variant — is tracked
    on *db* (#250), so a rollback of this transaction removes them with the
    rows. A matched asset is reused, never rewritten, so nothing of it is.
    """
    service = MediaService(db, settings)
    existing = await match_existing(db, settings, index)
    uploaded: dict[str, MediaAsset] = {}

    name_to_url: dict[str, str] = {}
    added = 0
    for bundle_name, entry in sorted(index.items()):
        original = entry.get("original_filename", bundle_name)
        asset = uploaded.get(entry["sha256"]) or existing.get(bundle_name)
        if asset is None:
            data = await asyncio.to_thread(blobs.get, entry["sha256"])
            upload = UploadFile(
                file=BytesIO(data),
                filename=original,
                headers=Headers(
                    {"content-type": entry.get("content_type", "application/octet-stream")}
                ),
            )
            asset = await service.upload(upload, folder=entry.get("folder"))
            track(db, _files_of(service, asset))
            uploaded[entry["sha256"]] = asset
            added += 1
        name_to_url[bundle_name] = service.url_for(asset.filename, asset.tenant_id)
    return name_to_url, added


def _files_of(service: MediaService, asset: MediaAsset) -> list[Path]:
    """The paths one fresh upload wrote, in its own tenant's directory."""
    folder = service.tenant_dir(asset.tenant_id)
    return [folder / name for name in media_file_names(asset.filename, asset.variants)]
