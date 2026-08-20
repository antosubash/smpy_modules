"""Cross-section admin search — articles, pages and media in one query set.

It lives in the news module because news is the only layer that can see all
three: it already depends on pagebuilder for the page and media tables, and
nothing depends on news. Putting it in pagebuilder instead would mean the base
module reaching up into a module that layers on top of it.

The three sections are searched separately rather than as one UNION. They have
genuinely different columns to match on — a page has body blocks, an article has
a category and tags, an asset has a filename — and a union would either lose
those or force every row into a shape none of them fit.
"""

from __future__ import annotations

import json
import re

from pagebuilder.models import NOT_TRASHED, MediaAsset, Page
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from news.contracts.schemas import SearchHit, SearchResults
from news.like import like_pattern
from news.models import NewsArticle, NewsArticleTag, NewsTag

#: Rows shown per section before the "N more" line takes over.
PER_SECTION = 5

#: Characters of body text either side of a match in the excerpt.
_SNIPPET_PADDING = 60


def excerpt(blocks: dict | None, q: str) -> str:
    """A window of body text around the first match, or ''.

    Reads the block JSON as text rather than walking the tree: the shape varies
    by block type and by Puck version, and every one of them ends up storing its
    prose as a JSON string either way. What this needs is the sentence around
    the hit, not a faithful render.
    """
    if not blocks or not q.strip():
        return ""
    haystack = json.dumps(blocks)
    # Collapse the JSON punctuation so the excerpt reads as prose rather than
    # as a fragment of a data structure.
    text = re.sub(r'["\{\}\[\],]|\\[a-z]', " ", haystack)
    text = re.sub(r"\s+", " ", text)
    at = text.lower().find(q.strip().lower())
    if at == -1:
        return ""
    start = max(0, at - _SNIPPET_PADDING)
    end = min(len(text), at + len(q) + _SNIPPET_PADDING)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


async def _article_ids_by_tag(db: AsyncSession, pattern: str) -> set[int]:
    """Articles carrying a tag that matches. Tags are the design's fourth
    searchable field and live two joins away, so they are resolved once here
    rather than joined into the main query."""
    rows = await db.execute(
        select(NewsArticleTag.article_id)
        .join(NewsTag, NewsTag.id == NewsArticleTag.tag_id)
        .where(NewsTag.name.ilike(pattern, escape="\\"))
    )
    return set(rows.scalars().all())


async def search(
    db: AsyncSession, q: str, *, include_drafts: bool = True, per_section: int = PER_SECTION
) -> SearchResults:
    """Search every section. Empty ``q`` returns empty results, not everything.

    ``include_drafts`` follows the same rule as the article listing: only an
    editor sees work that is not published yet.
    """
    results = SearchResults(query=q)
    if not q.strip():
        return results

    pattern = like_pattern(q)
    tagged = await _article_ids_by_tag(db, pattern)

    # ── Articles ──────────────────────────────────────────────────────
    article_match = or_(
        Page.title.ilike(pattern, escape="\\"),
        Page.slug.ilike(pattern, escape="\\"),
        NewsArticle.category.ilike(pattern, escape="\\"),
        NewsArticle.id.in_(tagged) if tagged else False,
    )
    article_base = (
        select(NewsArticle, Page)
        .join(Page, (Page.id == NewsArticle.page_id) & NOT_TRASHED)
        .where(article_match)
    )
    if not include_drafts:
        article_base = article_base.where(Page.status == "published")

    results.article_total = int(
        await db.scalar(select(func.count()).select_from(article_base.subquery())) or 0
    )
    for article, page in (
        await db.execute(article_base.order_by(NewsArticle.id.desc()).limit(per_section))
    ).all():
        results.articles.append(
            SearchHit(
                id=article.id or 0,
                title=page.title,
                subtitle=f"{article.category or 'Uncategorised'} · {page.status.value}",
                url=f"/news/articles/{article.id}/edit",
                excerpt=excerpt(page.draft_data, q),
            )
        )

    # ── Pages ─────────────────────────────────────────────────────────
    # Articles are pages, so they are excluded here — a hit that appeared in
    # both sections would make the counts add up to more than the archive holds.
    is_article = select(NewsArticle.page_id).where(NewsArticle.page_id == Page.id).exists()
    page_base = select(Page).where(
        NOT_TRASHED,
        ~is_article,
        or_(
            Page.title.ilike(pattern, escape="\\"),
            Page.slug.ilike(pattern, escape="\\"),
            # The body. A LIKE against the JSON column cast to text, evaluated
            # in the database — loading the blocks to search them in Python is
            # what made listings scale with content size rather than row count.
            # The cast is explicit: `func.cast` with an untyped target compiles
            # to NullType and the whole statement fails at DDL generation.
            cast(Page.draft_data, Text).ilike(pattern, escape="\\"),
        ),
    )
    if not include_drafts:
        page_base = page_base.where(Page.status == "published")

    results.page_total = int(
        await db.scalar(select(func.count()).select_from(page_base.subquery())) or 0
    )
    for page in (
        await db.execute(page_base.order_by(Page.id.desc()).limit(per_section))
    ).scalars():
        results.pages.append(
            SearchHit(
                id=page.id or 0,
                title=page.title,
                subtitle=f"/p/{page.slug} · {page.status.value}",
                url=f"/pagebuilder/{page.id}/edit",
                excerpt=excerpt(page.draft_data, q),
            )
        )

    # ── Media ─────────────────────────────────────────────────────────
    media_base = select(MediaAsset).where(
        or_(
            MediaAsset.original_filename.ilike(pattern, escape="\\"),
            MediaAsset.filename.ilike(pattern, escape="\\"),
        )
    )
    results.media_total = int(
        await db.scalar(select(func.count()).select_from(media_base.subquery())) or 0
    )
    for asset in (
        await db.execute(media_base.order_by(MediaAsset.id.desc()).limit(per_section))
    ).scalars():
        results.media.append(
            SearchHit(
                id=asset.id or 0,
                title=asset.original_filename,
                subtitle=asset.content_type,
                url="/pagebuilder/media",
                excerpt="",
            )
        )

    return results
