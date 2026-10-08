"""Writing a bundle back onto the live site.

Order is the whole point of this file. Media lands first so the pages that
reference it can resolve their sentinels; pages are then upserted in two
passes, because a parent may sort after its child and a redirect may point at a
page this same restore is creating. Layout goes last.

Nothing here commits. The caller owns the transaction, so a failure anywhere
rolls the whole restore back and a half-restored site is never a reachable
state.
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from starlette.datastructures import Headers

from pagebuilder.layout_service import LayoutService
from pagebuilder.media_service import MediaService
from pagebuilder.models import MediaAsset, Page, PageRedirect
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.snapshots.assets import from_sentinels
from pagebuilder.snapshots.blobs import BlobStore
from pagebuilder.snapshots.media_match import match_existing
from pagebuilder.snapshots.pages import MEDIA_FIELDS, PageKey, apply_payload
from pagebuilder.snapshots.plan import read_documents, redirect_locale


async def _restore_media(
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
                    {
                        "content-type": entry.get(
                            "content_type", "application/octet-stream"
                        )
                    }
                ),
            )
            asset = await service.upload(upload, folder=entry.get("folder"))
            uploaded[entry["sha256"]] = asset
            added += 1
        name_to_url[bundle_name] = service.url_for(asset.filename, asset.tenant_id)
    return name_to_url, added


async def _restore_pages(
    db: AsyncSession, bundled: dict[PageKey, dict[str, Any]], name_to_url: dict[str, str]
) -> tuple[dict[PageKey, Page], dict[PageKey, int], int, int]:
    """Pass one: upsert every page. Returns ``({key: page}, {key: id}, created, updated)``.

    Keyed by ``(locale, slug)`` because that is what the unique index is on:
    matching on the bare slug would make a German ``about`` overwrite the
    English one and then fail to create the page the bundle actually carried.

    Matching ignores the trash filter on purpose: a trashed page keeps its slug
    claimed *in its own language*, so restoring content under that key has to
    revive the row rather than insert a second one and trip the constraint.

    ``locale`` is passed to the constructor rather than through
    ``apply_payload``, because a page's language is fixed once it exists — a
    restore may create a page in a language, never move one between them.
    """
    result = await db.execute(select(Page))
    by_key = {(page.locale, page.slug): page for page in result.scalars().all()}

    created = 0
    updated = 0
    for key in sorted(bundled):
        locale, slug = key
        payload = dict(bundled[key])
        # Only keys the document actually carries: `apply_payload` and the
        # plan both treat an absent field as "leave it alone", so injecting
        # one here would overwrite a live value with None.
        for field in ("draft_data", "published_data", *MEDIA_FIELDS):
            if field in payload:
                payload[field] = from_sentinels(payload[field], name_to_url)
        page = by_key.get(key)
        if page is None:
            page = Page(slug=slug, locale=locale, title=payload.get("title", slug))
            db.add(page)
            by_key[key] = page
            created += 1
        else:
            updated += 1
        apply_payload(page, payload)
        # Restoring content under a claimed slug brings the page back.
        page.deleted_at = None

    await db.flush()
    ids = {key: page.id for key, page in by_key.items() if page.id}
    return by_key, ids, created, updated


async def _resolve_parents(
    db: AsyncSession,
    bundled: dict[PageKey, dict[str, Any]],
    by_key: dict[PageKey, Page],
    ids: dict[PageKey, int],
) -> None:
    """Pass two: wire ``parent_slug`` now that every page exists.

    The parent is looked up in the *child's own* language. Breadcrumbs never
    cross languages — ``PagesService._parent_in`` picks the parent's own
    counterpart for exactly that reason — so resolving the slug globally would
    let a German page's trail climb into the English tree whenever the German
    parent happened to be missing.

    *by_key* is pass one's map, not a fresh query: those are the same rows,
    already flushed, so re-reading the table would only return the objects the
    session is holding.

    An unresolvable parent becomes ``None`` rather than an error — ``parent_id``
    is already ``ondelete="SET NULL"`` precisely because a missing parent must
    not destroy the child.
    """
    for key, payload in bundled.items():
        page = by_key.get(key)
        if page is None:
            continue
        locale = key[0]
        parent_slug = payload.get("parent_slug")
        page.parent_id = ids.get((locale, parent_slug)) if parent_slug else None
    await db.flush()


async def _restore_redirects(
    db: AsyncSession, rows: list[dict[str, str]], ids: dict[PageKey, int]
) -> tuple[int, list[str]]:
    """Rebuild the redirect table, dropping any whose target does not exist.

    A redirect resolves within its own language: ``(locale, from_slug)`` is
    unique, and the target slug is looked up in that same locale, because a
    retired English address must not start resolving to the German page that
    happens to use the slug it pointed at.

    An unresolvable redirect is a 404 generator, so it is discarded and named
    rather than stored pointing at nothing.
    """
    await db.execute(delete(PageRedirect))
    kept = 0
    dropped: list[str] = []
    for row in rows:
        locale = redirect_locale(row)
        page_id = ids.get((locale, row.get("to_slug", "")))
        if page_id is None:
            dropped.append(row.get("from_slug", ""))
            continue
        db.add(
            PageRedirect(from_slug=row["from_slug"], locale=locale, page_id=page_id)
        )
        kept += 1
    await db.flush()
    return kept, dropped


async def apply_bundle(
    db: AsyncSession,
    settings: PagebuilderSettings,
    bundle_dir: Path,
    blobs: BlobStore,
    index: dict[str, Any],
    *,
    note: str | None = None,
) -> dict[str, Any]:
    """Restore *bundle_dir* onto the live site. Does not commit."""
    name_to_url, media_added = await _restore_media(db, settings, blobs, index)

    documents = await read_documents(bundle_dir)
    bundled = documents.pages
    by_key, ids, created, updated = await _restore_pages(db, bundled, name_to_url)
    await _resolve_parents(db, bundled, by_key, ids)
    redirects_kept, redirects_dropped = await _restore_redirects(
        db, documents.redirects, ids
    )

    layout = from_sentinels(documents.layout, name_to_url)
    await LayoutService(db).update(
        header_data=layout.get("header_data"),
        footer_data=layout.get("footer_data"),
        note=note,
    )

    return {
        "pages_created": created,
        "pages_updated": updated,
        "media_added": media_added,
        "redirects": redirects_kept,
        "redirects_dropped": redirects_dropped,
    }
