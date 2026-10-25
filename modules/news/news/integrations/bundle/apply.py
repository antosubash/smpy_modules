"""Writing a ``news/`` section onto the live site, inside the restore's transaction (#80).

Order: categories and tags first (articles link to tags), then articles, then
each bundled article's tag links, then the two redirect tables, rebuilt from
the bundle as pagebuilder rebuilds its own. Everything goes through
``ctx.db`` and is flushed, never committed: a failure anywhere — here or in
pagebuilder's part before it — rolls the whole restore back.

No revision row is written per restored article, mirroring pagebuilder: the
``pre_restore`` snapshot holds the previous state once.
"""

from __future__ import annotations

from typing import Any

from pagebuilder.contracts.bundle import RestoreContext, SectionApplied
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from news import redirects
from news.integrations.bundle import taxonomy
from news.integrations.bundle.documents import ArticleKey, batches, identity, write_article
from news.integrations.bundle.prepare import Prepared, prepare
from news.models import (
    NewsArticle,
    NewsArticleRedirect,
    NewsArticleTag,
    NewsCategory,
    NewsTag,
)


async def _articles(
    db: AsyncSession, prep: Prepared
) -> tuple[dict[ArticleKey, NewsArticle], list[ArticleKey]]:
    """Write every bundled article onto the row ``match_by_identity`` chose.

    Returns ``({key: row}, overwritten keys)``. Rows that move go through a
    scratch slug first, flushed, so two articles swapping addresses never
    collide. ``locale`` goes to the constructor and is never written after.
    """
    match = prep.match
    overwritten = [key for key in sorted(match.rows) if prep.changed(key)]
    if match.renames:
        for key, temp in match.temp_slugs().items():
            match.rows[key].slug = temp
        await db.flush()
    by_key = dict(match.rows)
    for key in match.creates:
        locale, slug = key
        row = NewsArticle(slug=slug, locale=locale, title=prep.articles[key].get("title", slug))
        db.add(row)
        by_key[key] = row
    for key in sorted(prep.articles):
        write_article(by_key[key], dict(match.writable(key, prep.articles[key])))
        db.add(by_key[key])
    await db.flush()
    return by_key, overwritten


async def _links(
    db: AsyncSession,
    prep: Prepared,
    by_key: dict[ArticleKey, NewsArticle],
    tags: dict[str, NewsTag],
) -> None:
    """Replace the tag links of every bundled article that carries ``tags``."""
    carried = {key: doc["tags"] for key, doc in prep.articles.items() if "tags" in doc}
    ids = [by_key[key].id for key in carried]
    if not ids:
        return
    for chunk in batches(ids):
        await db.execute(
            delete(NewsArticleTag).where(NewsArticleTag.article_id.in_(chunk))  # ty: ignore[unresolved-attribute]
        )
    for key, names in carried.items():
        for name in sorted(set(names)):
            db.add(NewsArticleTag(article_id=by_key[key].id or 0, tag_id=tags[name].id or 0))
    await db.flush()


async def _redirects(
    db: AsyncSession, prep: Prepared, by_key: dict[ArticleKey, NewsArticle]
) -> int:
    """Rebuild the article redirect table; return how many it holds for the bundle.

    A redirect resolves in its own language. Targets are the restored rows and
    the live articles the bundle left alone; one naming neither, or one from an
    address an article holds, is dropped (``Prepared.dropped_redirects``, which
    the plan lists). A row moved back to its snapshot slug keeps the
    address it was renamed to working, as pages do.
    """
    await db.execute(delete(NewsArticleRedirect))
    ids = {
        (row.locale, row.slug): row.id
        for row in [*by_key.values(), *prep.match.untouched]
        if row.deleted_at is None
    }
    kept = 0
    dropped = {(r["locale"], r["from_slug"]) for r in prep.dropped_redirects()}
    for entry in prep.redirects:
        article_id = ids.get((entry["locale"], entry["to_slug"]))
        if article_id is None or (entry["locale"], entry["from_slug"]) in dropped:
            continue
        db.add(
            NewsArticleRedirect(
                from_slug=entry["from_slug"], locale=entry["locale"], article_id=article_id
            )
        )
        kept += 1
    await db.flush()
    for (locale, old_slug), row in sorted(prep.match.rename_redirects().items()):
        assert row.id is not None
        await redirects.record(
            db, article_id=row.id, old_slug=old_slug, new_slug=row.slug, locale=locale
        )
    return kept


async def apply(ctx: RestoreContext) -> SectionApplied:
    """Restore the section; the audit record keeps identities and counts, never slugs."""
    prep = await prepare(ctx)
    respelled = prep.respelled()  # before the upsert renames the categories
    await taxonomy.upsert(ctx.db, NewsCategory, prep.categories, prep.category_rows)
    tags, moved = await taxonomy.upsert(ctx.db, NewsTag, prep.tags, prep.tag_rows)
    by_key, overwritten = await _articles(ctx.db, prep)
    await _links(ctx.db, prep, by_key, tags)
    kept = await _redirects(ctx.db, prep, by_key)
    tags_dropped = prep.dropped_tag_redirects()
    kept_tags = [r for r in prep.tag_redirects if r not in tags_dropped]
    await taxonomy.rebuild_tag_redirects(ctx.db, kept_tags, tags, moved)
    ctx.check_tenant()
    applied: dict[str, list[dict[str, Any]]] = {
        "created": [identity(by_key[key]) for key in sorted(prep.match.creates)],
        "overwritten": [identity(by_key[key]) for key in overwritten],
        # Articles outside the bundle whose category spelling the restore changed.
        "category_respelled": [identity(row) for row in respelled],
    }
    return SectionApplied(
        counts={
            "articles": len(prep.articles),
            "created": len(prep.match.creates),
            "overwritten": len(overwritten),
            "categories": len(prep.categories),
            "tags": len(prep.tags),
            "redirects": kept,
            "redirects_dropped": len(prep.dropped_redirects()) + len(tags_dropped),
            "category_respelled": len(respelled),
        },
        applied=applied,
    )
