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

from pagebuilder.media_files import resolve_media_root
from pagebuilder.models import MediaAsset
from pagebuilder.settings import PagebuilderSettings

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


async def match_existing(
    db: AsyncSession,
    settings: PagebuilderSettings,
    index: dict[str, Any],
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
        wanted = entry.get("sha256")
        original = entry.get("original_filename", bundle_name)
        for candidate in by_name.get(original, []):
            if candidate.id is None:
                continue
            if candidate.id not in digests:
                digests[candidate.id] = await asyncio.to_thread(
                    _digest_file, root / candidate.filename
                )
            if digests[candidate.id] == wanted:
                matched[bundle_name] = candidate
                break

    return matched


async def preview_urls(
    db: AsyncSession,
    settings: PagebuilderSettings,
    rows: list[Any],
) -> dict[str, str]:
    """Bundle name → the URL it would resolve to on this host, for the plan.

    Only what is already here can be known; the rest is uploaded at apply time.
    Resolving what we can keeps the plan from reporting every page carrying an
    image as changed purely because one side reads in sentinels.

    Lives beside ``match_existing`` so the plan and the apply cannot drift into
    matching by different rules.
    """
    from pagebuilder.media_service import MediaService

    index = {
        row.bundle_name: {
            "sha256": row.sha256,
            "original_filename": row.original_filename,
        }
        for row in rows
    }
    service = MediaService(db, settings)
    matched = await match_existing(db, settings, index)
    return {name: service.url_for(a.filename) for name, a in matched.items()}
