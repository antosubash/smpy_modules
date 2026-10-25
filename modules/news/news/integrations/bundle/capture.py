"""Writing the tenant's news content into a bundle's ``news/`` directory (#80).

Articles are read in batches of :data:`BATCH`, by id, and written one file per
article, so a capture never holds every body in memory at once. Trashed
articles are not captured: a snapshot is the site as it stands, the same rule
pages follow. Everything is read through ``ctx.db`` — the tenant filter keeps
it to the bound tenant.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from pagebuilder.contracts.bundle import CaptureContext, SectionCapture
from sqlmodel import select

from news.integrations.bundle.documents import (
    CATEGORIES_NAME,
    MEDIA_FIELDS,
    REDIRECTS_NAME,
    TAG_REDIRECTS_NAME,
    TAGS_NAME,
    article_doc,
    article_filename,
)
from news.models import (
    NOT_TRASHED,
    NewsArticle,
    NewsArticleRedirect,
    NewsArticleTag,
    NewsCategory,
    NewsTag,
    NewsTagRedirect,
)

BATCH = 200


async def _tag_names(ctx: CaptureContext, ids: list[int]) -> dict[int, list[str]]:
    result = await ctx.db.execute(
        select(NewsArticleTag.article_id, NewsTag.name)
        .join(NewsTag, NewsTag.id == NewsArticleTag.tag_id)
        .where(NewsArticleTag.article_id.in_(ids))  # ty: ignore[unresolved-attribute]
    )
    names: dict[int, list[str]] = defaultdict(list)
    for article_id, name in result.all():
        names[article_id].append(name)
    return names


def _portable(ctx: CaptureContext, doc: dict[str, Any]) -> dict[str, Any]:
    for field in MEDIA_FIELDS:
        doc[field] = ctx.to_portable(doc[field])
    return doc


async def _articles(ctx: CaptureContext) -> int:
    count, after = 0, 0
    while True:
        result = await ctx.db.execute(
            select(NewsArticle)
            .where(NOT_TRASHED, NewsArticle.id > after)  # ty: ignore[unsupported-operator]
            .order_by(NewsArticle.id)  # ty: ignore[invalid-argument-type]
            .limit(BATCH)
        )
        batch = list(result.scalars())
        if not batch:
            return count
        tags = await _tag_names(ctx, [a.id for a in batch if a.id is not None])
        docs = {
            article_filename(a.slug, a.locale): _portable(ctx, article_doc(a, tags[a.id or 0]))
            for a in batch
        }

        def write(docs: dict[str, dict[str, Any]] = docs) -> None:
            for name, doc in docs.items():
                ctx.write_json(name, doc)

        await asyncio.to_thread(write)
        count += len(batch)
        after = batch[-1].id or after


async def _taxonomy(ctx: CaptureContext) -> tuple[int, int]:
    categories = (
        await ctx.db.execute(
            select(NewsCategory).order_by(NewsCategory.position, NewsCategory.name)
        )
    ).scalars()
    cats = [{"name": c.name, "slug": c.slug, "position": c.position} for c in categories]
    tags = (await ctx.db.execute(select(NewsTag).order_by(NewsTag.name))).scalars()
    tag_docs = [{"name": t.name, "slug": t.slug} for t in tags]
    ctx.write_json(CATEGORIES_NAME, cats)
    ctx.write_json(TAGS_NAME, tag_docs)
    return len(cats), len(tag_docs)


async def _redirects(ctx: CaptureContext) -> int:
    """Article redirects to live articles, and every tag redirect."""
    result = await ctx.db.execute(
        select(NewsArticleRedirect.from_slug, NewsArticleRedirect.locale, NewsArticle.slug)
        .join(NewsArticle, NewsArticle.id == NewsArticleRedirect.article_id)
        .where(NOT_TRASHED)
    )
    articles = sorted(
        ({"from_slug": f, "locale": loc, "to_slug": to} for f, loc, to in result.all()),
        key=lambda r: (r["locale"], r["from_slug"]),
    )
    result = await ctx.db.execute(
        select(NewsTagRedirect.from_slug, NewsTag.slug).join(
            NewsTag, NewsTag.id == NewsTagRedirect.tag_id
        )
    )
    tags = sorted(
        ({"from_slug": f, "to_slug": to} for f, to in result.all()), key=lambda r: r["from_slug"]
    )
    ctx.write_json(REDIRECTS_NAME, articles)
    ctx.write_json(TAG_REDIRECTS_NAME, tags)
    return len(articles) + len(tags)


async def capture(ctx: CaptureContext) -> SectionCapture:
    ctx.check_tenant()
    articles = await _articles(ctx)
    categories, tags = await _taxonomy(ctx)
    redirects = await _redirects(ctx)
    return SectionCapture(
        counts={
            "articles": articles,
            "categories": categories,
            "tags": tags,
            "redirects": redirects,
        }
    )
