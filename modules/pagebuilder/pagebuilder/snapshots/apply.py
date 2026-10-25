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

from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder import redirects
from pagebuilder.layout_service import LayoutService
from pagebuilder.models import Page, PageRedirect
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.snapshots.apply_media import restore_media
from pagebuilder.snapshots.assets import from_sentinels
from pagebuilder.snapshots.blobs import BlobStore
from pagebuilder.snapshots.match import PageMatch, match_live
from pagebuilder.snapshots.pages import (
    MEDIA_FIELDS,
    PageKey,
    apply_payload,
    page_identity,
    page_state,
)
from pagebuilder.snapshots.plan import read_documents, redirect_locale


async def _restore_pages(
    db: AsyncSession,
    bundled: dict[PageKey, dict[str, Any]],
    match: PageMatch,
    name_to_url: dict[str, str],
) -> tuple[dict[PageKey, Page], dict[PageKey, int], set[PageKey], dict[PageKey, tuple]]:
    """Pass one: write every page onto the row :func:`match_pages` chose.

    Returns ``({bundle key: page}, {(locale, slug): id}, created keys,
    {matched key: state before})`` — the last two are what
    :func:`applied_outcomes` turns into the restore's audit record. The id map
    covers every page the tenant has, at its address *after* the restore, so
    parents and redirects resolve through restored slugs, never stale ones.

    A matched row is written whatever its slug is today: the bundle's slug is
    set explicitly, so a page renamed since the snapshot moves back rather
    than a second copy being inserted beside it. Rows that move go through a
    temporary slug first, flushed, so two pages swapping addresses — or a new
    page taking the address a renamed one is leaving — never collide on the
    unique index mid-flush.

    ``locale`` is passed to the constructor rather than through
    ``apply_payload``, because a page's language is fixed once it exists — a
    restore may create a page in a language, never move one between them.
    """
    before = {key: page_state(page) for key, page in match.rows.items()}
    if match.renames:
        for key, temp in match.temp_slugs().items():
            match.rows[key].slug = temp
        await db.flush()

    by_key = dict(match.rows)
    for key in match.creates:
        locale, slug = key
        page = Page(slug=slug, locale=locale, title=bundled[key].get("title", slug))
        db.add(page)
        by_key[key] = page
    for key in sorted(bundled):
        payload = dict(match.writable(key, bundled[key]))
        # Only keys the document actually carries: `apply_payload` and the
        # plan both treat an absent field as "leave it alone", so injecting
        # one here would overwrite a live value with None.
        for field in ("draft_data", "published_data", *MEDIA_FIELDS):
            if field in payload:
                payload[field] = from_sentinels(payload[field], name_to_url)
        page = by_key[key]
        page.slug = key[1]
        apply_payload(page, payload)
        # Restoring content onto a trashed row brings the page back.
        page.deleted_at = None

    await db.flush()
    every = [*by_key.values(), *match.untouched]
    ids = {(page.locale, page.slug): page.id for page in every if page.id}
    return by_key, ids, set(match.creates), before


def applied_outcomes(
    by_key: dict[PageKey, Page], created: set[PageKey], before: dict[PageKey, tuple]
) -> dict[str, list[dict[str, Any]]]:
    """``{"created": [...], "overwritten": [...]}`` — the pages this apply wrote.

    Each entry is :func:`page_identity`, not ``(locale, slug)``: a slug is
    reused after a purge and rewritten by a rename, an identity is neither. A
    page whose state came out identical to what it went in as is in neither
    list. Called after the parent pass, so ``parent_id`` is final.
    """
    return {
        "created": [page_identity(by_key[key]) for key in sorted(created)],
        "overwritten": [
            page_identity(page)
            for key, page in sorted(by_key.items())
            if key in before and page_state(page) != before[key]
        ],
    }


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
) -> tuple[set[PageKey], list[str]]:
    """Rebuild the redirect table, dropping any whose target does not exist.

    A redirect resolves within its own language: ``(locale, from_slug)`` is
    unique, and the target slug is looked up in that same locale, because a
    retired English address must not start resolving to the German page that
    happens to use the slug it pointed at.

    An unresolvable redirect is a 404 generator, so it is discarded and named
    rather than stored pointing at nothing.
    """
    await db.execute(delete(PageRedirect))
    kept: set[PageKey] = set()
    dropped: list[str] = []
    for row in rows:
        locale = redirect_locale(row)
        page_id = ids.get((locale, row.get("to_slug", "")))
        if page_id is None:
            dropped.append(row.get("from_slug", ""))
            continue
        db.add(PageRedirect(from_slug=row["from_slug"], locale=locale, page_id=page_id))
        kept.add((locale, row["from_slug"]))
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
    """Restore *bundle_dir* onto the live site. Does not commit.

    The result's ``applied`` key is for the caller's audit record, not for the
    response: it names the pages this apply actually wrote, by id.
    ``name_to_url`` is how this host now serves each bundled file, for the
    contributed sections the caller applies next.
    """
    documents = await read_documents(bundle_dir)
    bundled = documents.pages
    # Before media, which writes files no rollback removes.
    match = await match_live(db, bundled)
    name_to_url, media_added = await restore_media(db, settings, blobs, index)

    by_key, ids, created, before = await _restore_pages(db, bundled, match, name_to_url)
    await _resolve_parents(db, bundled, by_key, ids)
    applied = applied_outcomes(by_key, created, before)
    redirects_kept, redirects_dropped = await _restore_redirects(db, documents.redirects, ids)
    # After the rebuild, which would otherwise wipe them: a page moved back to
    # its snapshot slug keeps the address it was renamed to working. One that
    # replaces a bundle redirect from the same address is still one redirect.
    for (locale, old_slug), page in sorted(match.rename_redirects().items()):
        assert page.id is not None
        await redirects.record(
            db, page_id=page.id, old_slug=old_slug, new_slug=page.slug, locale=locale
        )
        # `record` also clears any redirect from the page's own address.
        redirects_kept.discard((locale, page.slug))
        redirects_kept.add((locale, old_slug))

    layout = from_sentinels(documents.layout, name_to_url)
    await LayoutService(db).update(
        header_data=layout.get("header_data"),
        footer_data=layout.get("footer_data"),
        note=note,
    )

    return {
        "pages_created": len(created),
        "pages_updated": len(before),
        "applied": applied,
        "name_to_url": name_to_url,  # for the contributed sections (#80); not a response field
        "media_added": media_added,
        "redirects": len(redirects_kept),
        "redirects_dropped": redirects_dropped,
    }
