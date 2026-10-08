"""Reading the live site into a bundle directory.

Runs in-process against the ORM — never over HTTP back into the running app.
Everything host-local is translated on the way out: media URLs become
``asset://`` sentinels, ``Page.parent_id`` becomes a slug, and
``PageRedirect.page_id`` becomes its target's slug.

Trashed pages are filtered out by the module's own ``NOT_TRASHED``, so a
snapshot holds exactly what the site serves and restoring one can never
resurrect something an editor binned.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder import locales
from pagebuilder.layout_service import LayoutService
from pagebuilder.media_files import (
    legacy_media_url,
    media_url,
    resolve_media_root,
    tenant_media_dir,
)
from pagebuilder.models import NOT_TRASHED, MediaAsset, Page, PageRedirect
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.snapshots.assets import bundle_names, to_sentinels
from pagebuilder.snapshots.blobs import BlobStore
from pagebuilder.snapshots.format import (
    FORMAT_VERSION,
    LAYOUT_NAME,
    MANIFEST_NAME,
    MEDIA_DIR,
    MEDIA_INDEX_NAME,
    PAGES_DIR,
    REDIRECTS_NAME,
)
from pagebuilder.snapshots.pages import MEDIA_FIELDS, page_to_payload


@dataclass
class CaptureResult:
    manifest: dict[str, Any]
    media: list[dict[str, Any]] = field(default_factory=list)
    size_bytes: int = 0


def _safe(segment: str) -> str:
    """*segment* with path separators neutralised.

    Slugs and locales are URL segments, but a separator sneaking into one
    would silently write outside ``pages/`` — so they are replaced rather
    than trusted. The authoritative values are inside the document either way.
    """
    return segment.replace("/", "_").replace(chr(92), "_")


def page_filename(slug: str, locale: str) -> str:
    """Filename for a page document, unique across languages.

    The default locale keeps the bare ``{slug}.json`` it has always had, so a
    monolingual site's bundle is byte-for-byte what earlier builds wrote and
    its diffs stay readable. Every other language is prefixed, because two
    languages may legitimately both publish ``about`` and one file cannot hold
    both — without the prefix the second page written would silently replace
    the first, losing a whole document with nothing in the manifest to say so.
    """
    stem = _safe(slug)
    return f"{stem}.json" if locales.is_default(locale) else f"{_safe(locale)}__{stem}.json"


def _write_json(path: Path, payload: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sorted keys and a trailing newline so two captures of unchanged content
    # produce byte-identical files — the round-trip test depends on it, and so
    # does a readable diff when a bundle is committed.
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    data = text.encode("utf-8")
    path.write_bytes(data)
    return len(data)


async def _media_maps(
    db: AsyncSession, settings: PagebuilderSettings
) -> tuple[dict[str, str], list[tuple[MediaAsset, str]], list[str]]:
    """Build ``{live url: bundle name}``, the assets to carry, and the missing.

    A row whose file is gone from disk is dropped from *both* maps together.
    Rewriting its URL to a sentinel the bundle then cannot carry would put an
    unresolvable ``asset://`` string into the captured content, and
    ``from_sentinels`` leaves those verbatim — so restoring would write the
    literal sentinel into a live page as an image src. Leaving the URL alone
    keeps the reference exactly as broken as it already is, and no worse.
    """
    result = await db.execute(select(MediaAsset).order_by(MediaAsset.id.asc()))
    assets = list(result.scalars().all())
    names = bundle_names([(a.id, a.original_filename) for a in assets if a.id])
    prefix = settings.media_url_prefix
    root = resolve_media_root(settings.media_root)

    url_to_name: dict[str, str] = {}
    present: list[tuple[MediaAsset, str]] = []
    missing: list[str] = []
    for asset in assets:
        if not asset.id:
            continue
        if not (tenant_media_dir(root, asset.tenant_id) / asset.filename).is_file():
            missing.append(asset.original_filename)
            continue
        # Both URLs the file is served at: content saved before per-tenant
        # media (#38) still carries the flat one.
        url_to_name[media_url(prefix, asset.filename, asset.tenant_id)] = names[asset.id]
        url_to_name[legacy_media_url(prefix, asset.filename)] = names[asset.id]
        present.append((asset, names[asset.id]))
    return url_to_name, present, missing


async def _capture_pages(
    db: AsyncSession, dest: Path, url_to_name: dict[str, str]
) -> tuple[list[dict[str, Any]], int]:
    result = await db.execute(
        select(Page).where(NOT_TRASHED).order_by(Page.locale.asc(), Page.slug.asc())
    )
    pages = list(result.scalars().all())
    slug_by_id = {page.id: page.slug for page in pages}

    entries: list[dict[str, Any]] = []
    documents: list[tuple[Path, dict[str, Any]]] = []
    for page in pages:
        # A parent is always its child's own counterpart — `_parent_in` picks
        # the parent's sibling in the child's language precisely so a
        # breadcrumb never crosses one — so the slug alone names it, read back
        # within this page's locale on restore.
        parent_slug = slug_by_id.get(page.parent_id) if page.parent_id else None
        payload = page_to_payload(page, parent_slug)
        for key in ("draft_data", "published_data", *MEDIA_FIELDS):
            payload[key] = to_sentinels(payload[key], url_to_name)
        documents.append(
            (dest / PAGES_DIR / page_filename(page.slug, page.locale), payload)
        )
        entries.append(
            {
                "slug": page.slug,
                "locale": page.locale,
                "title": page.title,
                "status": page.status.value,
                "parent_slug": parent_slug,
            }
        )
    # Off the event loop for the same reason `_capture_media` is: one
    # serialize + write per page, unbounded by the number of pages. The ORM
    # work above has to stay on the loop, so only the writes are offloaded.
    written = await asyncio.to_thread(
        lambda: sum(_write_json(path, payload) for path, payload in documents)
    )
    return entries, written


async def _capture_layout(
    db: AsyncSession, dest: Path, url_to_name: dict[str, str]
) -> tuple[dict[str, int], int]:
    layout = await LayoutService(db).get()
    payload = {
        "header_data": to_sentinels(layout.header_data, url_to_name),
        "footer_data": to_sentinels(layout.footer_data, url_to_name),
    }
    written = _write_json(dest / LAYOUT_NAME, payload)
    counts = {
        "header": len(payload["header_data"].get("content", []) or []),
        "footer": len(payload["footer_data"].get("content", []) or []),
    }
    return counts, written


async def _capture_redirects(db: AsyncSession, dest: Path) -> tuple[int, int]:
    # `PageRedirect.locale` rather than the target page's: the two always
    # agree today, but the redirect is the row the unique index is on, so it
    # is the one whose language decides where the old address resolved.
    result = await db.execute(
        select(PageRedirect.from_slug, PageRedirect.locale, Page.slug)
        .join(Page, Page.id == PageRedirect.page_id)
        .where(NOT_TRASHED)
        .order_by(PageRedirect.locale.asc(), PageRedirect.from_slug.asc())
    )
    rows = [
        {"from_slug": from_slug, "locale": locale, "to_slug": to_slug}
        for from_slug, locale, to_slug in result
    ]
    return len(rows), _write_json(dest / REDIRECTS_NAME, rows)


def _capture_media(
    dest: Path,
    blobs: BlobStore,
    settings: PagebuilderSettings,
    assets: list[tuple[MediaAsset, str]],
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Copy each asset's bytes into the blob store and write the index.

    *assets* has already been narrowed to rows whose file was on disk, by
    ``_media_maps`` — the same pass that decides which URLs become sentinels,
    so the two cannot disagree about what the bundle carries. Anything still
    unreadable here vanished mid-capture; it is reported rather than fatal,
    as a missing file always has been (issue #14).
    """
    root = resolve_media_root(settings.media_root)
    index: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    total = 0

    for asset, bundle_name in assets:
        source = tenant_media_dir(root, asset.tenant_id) / asset.filename
        if not source.is_file():
            missing.append(asset.original_filename)
            continue
        data = source.read_bytes()
        sha256 = blobs.put(data)
        total += len(data)
        index[bundle_name] = {
            "sha256": sha256,
            "original_filename": asset.original_filename,
            "content_type": asset.content_type,
            "folder": asset.folder,
        }
        rows.append({"bundle_name": bundle_name, **index[bundle_name]})

    total += _write_json(dest / MEDIA_DIR / MEDIA_INDEX_NAME, index)
    return rows, missing, total


async def capture(
    db: AsyncSession,
    settings: PagebuilderSettings,
    dest: Path,
    blobs: BlobStore,
) -> CaptureResult:
    """Write the live site into *dest* as a bundle directory.

    *dest* is emptied first. Writing into a directory that already holds a
    bundle would *merge* with it — the new pages land beside the old ones and
    the snapshot claims content the site never had. Snapshot ids normally make
    that impossible, but they come from the database while these files live on
    disk: restore a database backup without the filesystem and the next
    snapshot inherits a previous one's pages.
    """
    if dest.exists():
        await asyncio.to_thread(shutil.rmtree, dest)
    dest.mkdir(parents=True, exist_ok=True)
    url_to_name, assets, missing = await _media_maps(db, settings)

    pages, pages_bytes = await _capture_pages(db, dest, url_to_name)
    layout_counts, layout_bytes = await _capture_layout(db, dest, url_to_name)
    redirect_count, redirect_bytes = await _capture_redirects(db, dest)
    # Off the event loop: one read + SHA-256 + write per asset, unbounded by
    # the size of the media library. `media_service` offloads its own image
    # work the same way.
    media_rows, vanished, media_bytes = await asyncio.to_thread(
        _capture_media, dest, blobs, settings, assets
    )
    missing = sorted(missing + vanished)

    manifest = {
        "format_version": FORMAT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "pages": pages,
        "layout": layout_counts,
        "counts": {
            "pages": len(pages),
            "redirects": redirect_count,
            "media": len(media_rows),
        },
        "missing_media": missing,
    }
    # Written last: a bundle interrupted mid-capture then has no manifest and
    # is self-evidently incomplete rather than plausibly whole.
    size = pages_bytes + layout_bytes + redirect_bytes + media_bytes
    size += _write_json(dest / MANIFEST_NAME, manifest)
    return CaptureResult(manifest=manifest, media=media_rows, size_bytes=size)
