"""Restoring categories, tags and tag redirects from a ``news/`` section (#80).

Both are upserted by *name* — the value an article carries — and given the
bundle's slug (and, for a category, its position). Rows the bundle does not
carry are left alone. Rows whose slug changes go through a scratch slug first,
flushed, so two of them swapping slugs never collide on the unique index
mid-flush. ``prepare`` has already refused a slug held by a row the bundle
does not carry.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from news import tag_redirects
from news.models import NewsCategory, NewsTag, NewsTagRedirect


async def upsert[Row: (NewsCategory, NewsTag)](
    db: AsyncSession,
    model: type[Row],
    entries: list[dict[str, Any]],
    live: dict[str, Row],
) -> tuple[dict[str, Row], dict[str, str]]:
    """``({name: row}, {name: slug before})`` — the latter for every row that moved."""
    moved = {
        e["name"]: live[e["name"]].slug
        for e in entries
        if e["name"] in live and live[e["name"]].slug != e["slug"]
    }
    for name in moved:
        live[name].slug = f"~restoring-{live[name].id}"
    if moved:
        await db.flush()
    rows = dict(live)
    for entry in entries:
        row = rows.get(entry["name"])
        if row is None:
            row = model(name=entry["name"], slug=entry["slug"])
            rows[entry["name"]] = row
        row.slug = entry["slug"]
        if "position" in entry and isinstance(row, NewsCategory):
            row.position = entry["position"]
        db.add(row)
    await db.flush()
    return rows, moved


async def rebuild_tag_redirects(
    db: AsyncSession,
    entries: list[dict[str, Any]],
    tags: dict[str, NewsTag],
    moved: dict[str, str],
) -> list[dict[str, Any]]:
    """Replace every tag redirect with the bundle's; return the ones dropped.

    Resolved by the target's slug after the upsert. A redirect from a slug a
    tag now holds is dropped too: the live tag already answers there, and the
    row would wake up pointing elsewhere the day that tag is renamed. A tag
    moved back to its snapshot slug keeps the slug it was renamed to working.
    """
    await db.execute(delete(NewsTagRedirect))
    by_slug = {tag.slug: tag for tag in tags.values()}
    dropped: list[dict[str, Any]] = []
    for entry in entries:
        target = by_slug.get(entry["to_slug"])
        if target is None or entry["from_slug"] in by_slug:
            dropped.append({"from_slug": entry["from_slug"]})
            continue
        db.add(NewsTagRedirect(from_slug=entry["from_slug"], tag_id=target.id or 0))
    await db.flush()
    for name, old in sorted(moved.items()):
        tag = tags[name]
        if old not in by_slug and tag.id is not None:
            await tag_redirects.record(db, tag_id=tag.id, old_slug=old, new_slug=tag.slug)
    return dropped
