"""Deciding whether a bundled file is already in this host's media library.

``original_filename`` is a label, not an identity — two different pictures can
share one, which is exactly why ``bundle_names`` has to mint ``hero~2.jpg``.
Matching on the name alone means a bundle restored onto a host that happens to
have its own ``hero.jpg`` silently repoints every page at the wrong picture and
reports nothing, and moving content between hosts is the whole point of a
bundle.

So the name narrows the candidates and the **digest decides**. No schema change
is needed for that: only assets whose name actually collides get hashed, and
each one at most once per restore.

The digest compared is the bundle's *and* the one its bytes would be stored
with (#356): with ``media_strip_metadata`` on, an upload is cleaned of its
metadata, so a restored file no longer hashes to its bundle digest. Without
the second, every later restore of the same bundle would upload a duplicate
and repoint the pages at it. :func:`clean_bytes` is deterministic and leaves a
clean file as it is, so for a bundle taken on this host the two are one.

Both the plan and the apply resolve sentinels through this, deliberately. If
they disagreed, the plan would resolve a bundle entry to a URL the apply then
declined to reuse — reporting a page as unchanged while its image was about to
change underneath the approver.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.content.snapshots.blobs import BlobStore
from pagebuilder.core.settings import PagebuilderSettings
from pagebuilder.media.media_files import resolve_media_root, tenant_media_dir
from pagebuilder.media.media_images import (
    SNIFF_BYTES,
    TooManyPixelsError,
    sniff_content_type,
)
from pagebuilder.media.media_metadata import MetadataNotRemovedError, clean_bytes
from pagebuilder.models import MediaAsset

_CHUNK = 1024 * 1024


def _digest_file(path: Path) -> str | None:
    """sha256 of *path*, or ``None`` if it is not readable.

    A row whose file is missing is a real divergence (issue #14) and must read
    as "no match" rather than raise — the restore then uploads the bundle's own
    copy, which is the repair.
    """
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _stored_digest(blobs: BlobStore, sha256: str) -> str | None:
    """sha256 of the bundle file as an upload would store it, if that differs.

    Cleaned as the type its bytes sniff as, as the upload does, never the type
    the bundle's index declares for it.
    """
    try:
        data = blobs.get(sha256)
        cleaned = clean_bytes(data, sniff_content_type(data[:SNIFF_BYTES]) or "")
    except (OSError, ValueError, MetadataNotRemovedError, TooManyPixelsError):
        return None  # the upload refuses it, or the blob is gone: nothing to match
    return hashlib.sha256(cleaned).hexdigest() if cleaned is not None else None


async def _wanted(
    entry: dict[str, Any], settings: PagebuilderSettings, blobs: BlobStore
) -> set[str]:
    sha = entry.get("sha256")
    wanted = {sha} if sha else set()
    if sha and settings.media_strip_metadata:
        stored = await asyncio.to_thread(_stored_digest, blobs, sha)
        if stored:
            wanted.add(stored)
    return wanted


async def match_existing(
    db: AsyncSession,
    settings: PagebuilderSettings,
    index: dict[str, Any],
    blobs: BlobStore,
) -> dict[str, MediaAsset]:
    """Map each bundle name to the live asset that genuinely holds its bytes.

    A bundle name is absent from the result when this host has nothing with
    that content — the caller uploads the bundle's copy instead.
    """
    result = await db.execute(select(MediaAsset))
    by_name: dict[str, list[MediaAsset]] = defaultdict(list)
    for asset in result.scalars().all():
        by_name[asset.original_filename].append(asset)

    root = resolve_media_root(settings.media_root)
    digests: dict[int, str | None] = {}
    matched: dict[str, MediaAsset] = {}

    for bundle_name, entry in sorted(index.items()):
        original = entry.get("original_filename", bundle_name)
        candidates = by_name.get(original, [])
        # Only a name that collides costs a hash, or a strip in memory.
        wanted = await _wanted(entry, settings, blobs) if candidates else set()
        for candidate in candidates:
            if candidate.id is None:
                continue
            if candidate.id not in digests:
                digests[candidate.id] = await asyncio.to_thread(
                    _digest_file,
                    tenant_media_dir(root, candidate.tenant_id) / candidate.filename,
                )
            if digests[candidate.id] in wanted:
                matched[bundle_name] = candidate
                break

    return matched


async def preview_urls(
    db: AsyncSession,
    settings: PagebuilderSettings,
    rows: list[Any],
    blobs: BlobStore,
) -> dict[str, str]:
    """Bundle name → the URL it would resolve to on this host, for the plan.

    Only what is already here can be known; the rest is uploaded at apply time.
    Resolving what we can keeps the plan from reporting every page carrying an
    image as changed purely because one side reads in sentinels.

    Lives beside ``match_existing`` so the plan and the apply cannot drift into
    matching by different rules.
    """
    from pagebuilder.media.media_service import MediaService

    index = {
        row.bundle_name: {
            "sha256": row.sha256,
            "original_filename": row.original_filename,
            "content_type": row.content_type,
        }
        for row in rows
    }
    service = MediaService(db, settings)
    matched = await match_existing(db, settings, index, blobs)
    return {name: service.url_for(a.filename, a.tenant_id) for name, a in matched.items()}
