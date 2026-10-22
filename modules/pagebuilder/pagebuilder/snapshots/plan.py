"""What restoring a bundle would do, computed before anything is written.

The plan is the screen an approver reads, so it has to answer the question they
actually have: *what am I about to lose?* Hence the emphasis on overwritten
pages and on saying plainly that pages absent from the bundle are kept rather
than deleted — restore never deletes, and an approver who assumes otherwise
will reject a perfectly good bundle.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.diff import block_diff
from pagebuilder.models import Page, PageRedirect
from pagebuilder.snapshots.assets import from_sentinels
from pagebuilder.snapshots.format import LAYOUT_NAME, PAGES_DIR, REDIRECTS_NAME
from pagebuilder.snapshots.match import PageMatch, match_live
from pagebuilder.snapshots.pages import (
    PAGE_FIELDS,
    PageKey,
    normalise_locale,
    payload_key,
)

_COMPARED_FIELDS = tuple(f for f in PAGE_FIELDS if f not in ("draft_data", "published_data"))


def read_pages(bundle_dir: Path) -> dict[PageKey, dict[str, Any]]:
    """Every page document in *bundle_dir*, keyed by ``(locale, slug)``.

    Keyed by what the document itself says rather than by its filename: the
    filename is sanitised for the filesystem, the document is the truth. The
    locale is part of the key because a slug is only unique within one — key
    by slug alone and a bilingual site's two ``about`` pages collapse into
    whichever file happened to sort last.
    """
    pages: dict[PageKey, dict[str, Any]] = {}
    directory = bundle_dir / PAGES_DIR
    if not directory.is_dir():
        return pages
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text())
        pages[payload_key(payload)] = payload
    return pages


def read_redirects(bundle_dir: Path) -> list[dict[str, str]]:
    path = bundle_dir / REDIRECTS_NAME
    return json.loads(path.read_text()) if path.is_file() else []


def read_layout(bundle_dir: Path) -> dict[str, Any]:
    path = bundle_dir / LAYOUT_NAME
    return json.loads(path.read_text()) if path.is_file() else {}


class BundleDocuments(NamedTuple):
    """Everything a bundle's JSON says, read once."""

    pages: dict[PageKey, dict[str, Any]]
    redirects: list[dict[str, str]]
    layout: dict[str, Any]


async def read_documents(bundle_dir: Path) -> BundleDocuments:
    """Read every bundle document, off the event loop, in one pass.

    Both callers are request handlers, and a site with hundreds of pages is
    hundreds of blocking reads and parses — the same reason ``service`` already
    offloads unzipping and hashing. One offload rather than one per document,
    and one read of each file rather than one per consumer.
    """
    return await asyncio.to_thread(
        lambda: BundleDocuments(
            read_pages(bundle_dir),
            read_redirects(bundle_dir),
            read_layout(bundle_dir),
        )
    )


def redirect_locale(row: dict[str, str]) -> str:
    """The language a redirect row belongs to, defaulting a v1 bundle's absence.

    The mirror of :func:`~pagebuilder.snapshots.pages.payload_locale`, and for
    the same reason: ``redirects.json`` gained the key in version 2, so a row
    without one came from a site that had only the default locale.
    """
    return normalise_locale(row.get("locale"))


def _fields_differ(
    payload: dict[str, Any], page: Page, name_to_url: dict[str, str]
) -> bool:
    """Compare only the fields the bundle actually carries.

    ``apply_payload`` sets a field only when the payload has it, so comparing
    absent keys against a column default would report drift for a change the
    restore would never make. The plan has to describe the apply that will
    happen, not a stricter hypothetical one — which is also why the media
    fields are resolved first: apply writes the resolved URL, so comparing the
    raw sentinel would report a change on every restore.
    """
    return any(
        from_sentinels(payload[field], name_to_url) != getattr(page, field)
        for field in _COMPARED_FIELDS
        if field in payload
    )


async def build_plan(
    db: AsyncSession,
    bundle_dir: Path,
    name_to_url: dict[str, str],
) -> dict[str, Any]:
    """Classify everything the bundle would do against the live site.

    *name_to_url* resolves the bundle's sentinels the way apply would, so a
    page is only reported as changed when its content genuinely differs — not
    merely because one side is written in sentinels and the other in URLs.
    """
    documents = await read_documents(bundle_dir)
    bundled = documents.pages

    # Unfiltered on purpose: a trashed page still holds its slug and its group
    # in the unique indexes, and restoring onto it revives it — classifying it
    # as "new" would promise a fresh page while apply overwrites recoverable
    # content. The matcher is apply's own, so this describes the rows it writes.
    match = await match_live(db, bundled)

    new: list[dict[str, Any]] = []
    overwritten: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []

    for key in sorted(bundled):
        locale, slug = key
        page = match.rows.get(key)
        payload = match.writable(key, bundled[key])
        entry: dict[str, Any] = {"slug": slug, "locale": locale, "title": payload.get("title")}
        if page is None:
            new.append(entry)
            continue
        trashed = page.deleted_at is not None
        if trashed:
            entry["revived"] = True
        if key in match.renames:
            entry["renamed_from"] = match.renames[key]
        incoming_draft = from_sentinels(payload.get("draft_data"), name_to_url)
        incoming_published = from_sentinels(payload.get("published_data"), name_to_url)
        content_differs = (
            ("draft_data" in payload and incoming_draft != page.draft_data)
            or (
                "published_data" in payload
                and incoming_published != page.published_data
            )
            or ("status" in payload and payload["status"] != page.status.value)
        )
        # Neither a trashed nor a renamed page is ever "unchanged": apply
        # clears `deleted_at` and moves the slug back, so even byte-identical
        # content means the page changes.
        fields_differ = _fields_differ(payload, page, name_to_url)
        moved = trashed or key in match.renames
        if not moved and not content_differs and not fields_differ:
            unchanged.append(entry)
            continue
        blocks = block_diff(page.draft_data, incoming_draft)
        overwritten.append(
            {
                **entry,
                "added": len(blocks["added"]),
                "removed": len(blocks["removed"]),
                "changed": len(blocks["changed"]),
            }
        )

    untouched = [
        {"slug": page.slug, "locale": page.locale, "title": page.title}
        for page in sorted(match.untouched, key=lambda p: (p.locale, p.slug))
        if page.deleted_at is None
    ]

    return {
        "pages": {
            "new": new,
            "overwritten": overwritten,
            "unchanged": unchanged,
            "untouched": untouched,
        },
        "layout": _layout_plan(documents.layout, name_to_url),
        "redirects": await _redirect_plan(db, documents.redirects, match),
    }


def _layout_plan(raw_layout: dict[str, Any], name_to_url: dict[str, str]) -> dict[str, Any]:
    """Block counts per side, and whether the bundle carries that side at all.

    ``LayoutService.update`` reads ``None`` as "no change requested", so a
    bundle with no ``layout.json`` — or with only one of the two keys — leaves
    the live layout untouched. Reporting a bare ``0`` for that case told an
    approver the header would be emptied when it would not be, and read
    identically to a bundle carrying an explicitly empty header, which *does*
    empty it. The flags keep those two apart.
    """
    layout = from_sentinels(raw_layout, name_to_url)
    plan: dict[str, Any] = {}
    for side, key in (("header", "header_data"), ("footer", "footer_data")):
        carried = layout.get(key)
        plan[side] = len((carried or {}).get("content", []) or [])
        plan[f"{side}_present"] = carried is not None
    return plan


async def _redirect_plan(
    db: AsyncSession, bundled: list[dict[str, str]], match: PageMatch
) -> dict[str, Any]:
    """Which redirects a restore would add, remove, or drop as unresolvable.

    Keyed by ``(locale, from_slug)`` throughout, matching the unique index:
    the same retired slug can exist in two languages pointing at two different
    pages, and collapsing them onto the bare slug would report one as removed
    the moment the other appeared in a bundle.

    The three lists report slugs, not pairs, because the screen only counts
    them and joins them into a sentence. One consequence is deliberate: a slug
    retired in two languages appears twice, which is two redirects and so two
    entries — deduplicating would undercount the work a restore is about to do.

    Targets resolve against the addresses pages hold *after* the restore, and
    a page the restore moves back to its old slug also leaves a redirect at
    the newer one — apply records both, so both are counted here.
    """
    known_pages = match.final_keys()
    result = await db.execute(select(PageRedirect.locale, PageRedirect.from_slug))
    existing = {(locale, from_slug) for locale, from_slug in result}

    def target(row: dict[str, str]) -> PageKey:
        return redirect_locale(row), row.get("to_slug", "")

    def source(row: dict[str, str]) -> PageKey:
        return redirect_locale(row), row.get("from_slug", "")

    dropped = [source(r) for r in bundled if target(r) not in known_pages]
    keepable = {source(r) for r in bundled if target(r) in known_pages}
    keepable |= set(match.rename_redirects())
    # `removed` and `dropped` are shown side by side, so they have to be
    # disjoint: a redirect that exists today *and* is in the bundle with a
    # missing target is one redirect, not two. It is reported as dropped —
    # the more specific fact, and the one that names the slug.
    return {
        "added": [slug for _, slug in sorted(keepable - existing)],
        "removed": [slug for _, slug in sorted(existing - keepable - set(dropped))],
        "dropped": [slug for _, slug in sorted(dropped)],
    }
