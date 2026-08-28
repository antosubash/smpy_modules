"""What restoring a bundle would do, computed before anything is written.

The plan is the screen an approver reads, so it has to answer the question they
actually have: *what am I about to lose?* Hence the emphasis on overwritten
pages and on saying plainly that pages absent from the bundle are kept rather
than deleted — restore never deletes, and an approver who assumes otherwise
will reject a perfectly good bundle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.diff import block_diff
from pagebuilder.models import NOT_TRASHED, Page, PageRedirect
from pagebuilder.snapshots.assets import from_sentinels
from pagebuilder.snapshots.format import LAYOUT_NAME, PAGES_DIR, REDIRECTS_NAME
from pagebuilder.snapshots.pages import PAGE_FIELDS

_COMPARED_FIELDS = tuple(f for f in PAGE_FIELDS if f not in ("draft_data", "published_data"))


def read_pages(bundle_dir: Path) -> dict[str, dict[str, Any]]:
    """Every page document in *bundle_dir*, keyed by the slug inside it.

    Keyed by the document's own ``slug`` rather than its filename: the filename
    is sanitised for the filesystem, the slug is the truth.
    """
    pages: dict[str, dict[str, Any]] = {}
    directory = bundle_dir / PAGES_DIR
    if not directory.is_dir():
        return pages
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text())
        pages[payload["slug"]] = payload
    return pages


def read_redirects(bundle_dir: Path) -> list[dict[str, str]]:
    path = bundle_dir / REDIRECTS_NAME
    return json.loads(path.read_text()) if path.is_file() else []


def read_layout(bundle_dir: Path) -> dict[str, Any]:
    path = bundle_dir / LAYOUT_NAME
    return json.loads(path.read_text()) if path.is_file() else {}


def _fields_differ(payload: dict[str, Any], page: Page) -> bool:
    """Compare only the fields the bundle actually carries.

    ``apply_payload`` sets a field only when the payload has it, so comparing
    absent keys against a column default would report drift for a change the
    restore would never make. The plan has to describe the apply that will
    happen, not a stricter hypothetical one.
    """
    return any(
        payload[field] != getattr(page, field)
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
    bundled = read_pages(bundle_dir)

    result = await db.execute(select(Page).where(NOT_TRASHED))
    live = {page.slug: page for page in result.scalars().all()}

    new: list[dict[str, Any]] = []
    overwritten: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []

    for slug in sorted(bundled):
        payload = bundled[slug]
        page = live.get(slug)
        entry = {"slug": slug, "title": payload.get("title")}
        if page is None:
            new.append(entry)
            continue
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
        if not content_differs and not _fields_differ(payload, page):
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
        {"slug": slug, "title": page.title}
        for slug, page in sorted(live.items())
        if slug not in bundled
    ]

    return {
        "pages": {
            "new": new,
            "overwritten": overwritten,
            "unchanged": unchanged,
            "untouched": untouched,
        },
        "layout": _layout_plan(bundle_dir, name_to_url),
        "redirects": await _redirect_plan(db, bundle_dir, set(bundled) | set(live)),
    }


def _layout_plan(bundle_dir: Path, name_to_url: dict[str, str]) -> dict[str, Any]:
    layout = from_sentinels(read_layout(bundle_dir), name_to_url)
    header = layout.get("header_data") or {}
    footer = layout.get("footer_data") or {}
    return {
        "header": len(header.get("content", []) or []),
        "footer": len(footer.get("content", []) or []),
    }


async def _redirect_plan(
    db: AsyncSession, bundle_dir: Path, known_slugs: set[str]
) -> dict[str, Any]:
    bundled = read_redirects(bundle_dir)
    result = await db.execute(select(PageRedirect.from_slug))
    existing = {row for (row,) in result}

    dropped = [r["from_slug"] for r in bundled if r.get("to_slug") not in known_slugs]
    keepable = {r["from_slug"] for r in bundled if r.get("to_slug") in known_slugs}
    return {
        "added": sorted(keepable - existing),
        "removed": sorted(existing - keepable),
        "dropped": sorted(dropped),
    }
