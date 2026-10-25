"""Restoring categories, tags and tag redirects from a ``news/`` section (#80).

A bundled category or tag lands on the live row with the same name *as the
admin compares names* — trimmed and case-insensitive (:func:`name_key`, the
rule ``category_service.find_by_name`` and ``tag_service`` apply) — so
importing ``Updates`` into a site that has ``updates`` restores that row
rather than creating a second one the admin would refuse. An exact spelling
wins over a case-only match; two live rows that both match only by case are
ambiguous and refuse the restore (409). The matched row takes the bundle's
spelling, slug and (for a category) position; renaming a category carries
the articles that use the old name, as ``category_service.rename`` does.

Rows whose slug changes go through a scratch slug first, flushed, so two of
them swapping slugs never collide on the unique index mid-flush. Rows the
bundle does not carry are left alone.
"""

from __future__ import annotations

from typing import Any

from pagebuilder.contracts.bundle import RestoreContext
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from news import tag_redirects
from news.integrations.bundle.documents import name_key
from news.models import NewsArticle, NewsCategory, NewsTag, NewsTagRedirect


def pair[Row: (NewsCategory, NewsTag)](
    ctx: RestoreContext, noun: str, bundled: list[dict[str, Any]], live: list[Row]
) -> dict[str, Row]:
    """Bundle name -> the live row it restores onto. Raises ``ctx.conflict``.

    Conflicts: a name only a case-insensitive comparison matches, against two
    live rows; or a bundled slug held by a live row no bundled entry claims —
    moving that row out of the way would change something nobody asked about.
    """
    exact = {row.name: row for row in live}
    pairs: dict[str, Row] = {}
    for entry in bundled:
        row = exact.get(entry["name"])
        if row is None:
            found = [r for r in live if name_key(r.name) == name_key(entry["name"])]
            if len(found) > 1:
                raise ctx.conflict(
                    f"the {noun} {entry['name']!r} matches {len(found)} {noun} names here "
                    f"({', '.join(sorted(r.name for r in found))}) — merge them first"
                )
            row = found[0] if found else None
        if row is not None:
            pairs[entry["name"]] = row
    claimed = {id(row) for row in pairs.values()}
    by_slug = {row.slug: row for row in live}
    for entry in bundled:
        holder = by_slug.get(entry["slug"])
        if holder is not None and id(holder) not in claimed:
            raise ctx.conflict(
                f"the {noun} slug {entry['slug']!r} now belongs to {holder.name!r}, not "
                f"{entry['name']!r} — rename that {noun} first"
            )
    return pairs


async def upsert[Row: (NewsCategory, NewsTag)](
    db: AsyncSession,
    model: type[Row],
    entries: list[dict[str, Any]],
    pairs: dict[str, Row],
) -> tuple[dict[str, Row], dict[str, str]]:
    """``({bundle name: row}, {bundle name: slug before})`` — the latter for rows that moved."""
    moved = {
        e["name"]: pairs[e["name"]].slug
        for e in entries
        if e["name"] in pairs and pairs[e["name"]].slug != e["slug"]
    }
    for name in moved:
        pairs[name].slug = f"~restoring-{pairs[name].id}"
    if moved:
        await db.flush()
    rows: dict[str, Row] = {}
    for entry in entries:
        row = pairs.get(entry["name"])
        if row is None:
            row = model(name=entry["name"], slug=entry["slug"])
        elif row.name != entry["name"]:
            if isinstance(row, NewsCategory):
                await db.execute(
                    update(NewsArticle)
                    .where(NewsArticle.category == row.name)  # ty: ignore[invalid-argument-type]
                    .values(category=entry["name"])
                )
            row.name = entry["name"]
        row.slug = entry["slug"]
        if "position" in entry and isinstance(row, NewsCategory):
            row.position = entry["position"]
        db.add(row)
        rows[entry["name"]] = row
    await db.flush()
    return rows, moved


async def rebuild_tag_redirects(
    db: AsyncSession,
    kept: list[dict[str, Any]],
    tags: dict[str, NewsTag],
    moved: dict[str, str],
) -> None:
    """Replace every tag redirect with *kept* (the bundle's, minus the plan's drops).

    Resolved by the target's slug after the upsert. A tag moved back to its
    snapshot slug keeps the slug it was renamed to working, unless a tag now
    holds that slug.
    """
    await db.execute(delete(NewsTagRedirect))
    by_slug = {tag.slug: tag for tag in (await db.execute(select(NewsTag))).scalars()}
    for entry in kept:
        target = by_slug[entry["to_slug"]]
        db.add(NewsTagRedirect(from_slug=entry["from_slug"], tag_id=target.id or 0))
    await db.flush()
    for name, old in sorted(moved.items()):
        tag = tags[name]
        if old not in by_slug and tag.id is not None:
            await tag_redirects.record(db, tag_id=tag.id, old_slug=old, new_slug=tag.slug)
