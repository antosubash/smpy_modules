"""Cross-section admin search.

Articles are this module's own and are always searched. Pages and media belong
to pagebuilder, so they are searched only where that module happens to be
installed — see :mod:`news.integrations.pagebuilder`. On a host running news
alone the screen is an article search, which is the honest answer rather than a
degraded one.

The sections are searched separately rather than as one UNION. They have
genuinely different columns to match on — a page has body blocks, an article has
a category and tags, an asset has a filename — and a union would either lose
those or force every row into a shape none of them fit.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from news import constants
from news.contracts.schemas import SearchHit, SearchResults
from news.integrations import pagebuilder
from news.like import like_pattern
from news.models import NOT_TRASHED, NewsArticle, NewsArticleTag, NewsTag

#: Rows shown per section before the "N more" line takes over.
PER_SECTION = 5

#: Characters of body text either side of a match in the excerpt.
_SNIPPET_PADDING = 60


def _string_values(value: object) -> Iterator[str]:
    """Every string *value* in a block tree, ignoring the keys.

    Generic rather than shape-aware on purpose: the block schema varies by type
    and by Puck version, but prose is always stored as a string somewhere in
    here, and a walk that only collects values needs to know none of that.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _string_values(item)


def excerpt(blocks: dict | None, q: str) -> str:
    """A window of body text around the first match, or ''.

    Values only. Stripping the JSON *punctuation* out of ``json.dumps`` was not
    enough — it left the keys behind, so a document whose match sat near the
    start produced "root : props : title : … content : zones :" on the search
    screen, which reads as a dump of the data structure rather than as a
    sentence from the page.
    """
    if not blocks or not q.strip():
        return ""
    text = re.sub(r"\s+", " ", " ".join(_string_values(blocks)))
    at = text.lower().find(q.strip().lower())
    if at == -1:
        return ""
    start = max(0, at - _SNIPPET_PADDING)
    end = min(len(text), at + len(q) + _SNIPPET_PADDING)
    return (
        ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")
    )


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


async def _search_articles(
    db: AsyncSession, results: SearchResults, q: str, pattern: str, *, include_drafts: bool,
    per_section: int,
) -> None:
    tagged = await _article_ids_by_tag(db, pattern)
    match = or_(
        NewsArticle.title.ilike(pattern, escape="\\"),
        NewsArticle.slug.ilike(pattern, escape="\\"),
        NewsArticle.category.ilike(pattern, escape="\\"),
        # The body. Articles could not be searched on it while it lived on a
        # joined page: the pages section deliberately excluded every row that
        # was an article, so an article's prose was in the index of neither
        # section and searching for a phrase from one found nothing.
        #
        # A LIKE against the JSON column cast to text, evaluated in the
        # database — loading the blocks to search them in Python is what made
        # listings scale with content size rather than row count. The cast is
        # explicit: `func.cast` with an untyped target compiles to NullType and
        # the whole statement fails at DDL generation.
        cast(NewsArticle.draft_data, Text).ilike(pattern, escape="\\"),
        NewsArticle.id.in_(tagged) if tagged else False,
    )
    base = select(NewsArticle).where(NOT_TRASHED, match)
    if not include_drafts:
        base = base.where(NewsArticle.status == "published")

    results.article_total = int(
        await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    )
    for article in (
        await db.execute(base.order_by(NewsArticle.id.desc()).limit(per_section))
    ).scalars():
        results.articles.append(
            SearchHit(
                id=article.id or 0,
                title=article.title,
                subtitle=f"{article.category or constants.UNCATEGORISED_LABEL} · "
                f"{article.status.value}",
                url=constants.ARTICLE_EDITOR_URL.format(article_id=article.id or 0),
                excerpt=excerpt(article.draft_data, q),
            )
        )


async def search(
    db: AsyncSession, q: str, *, include_drafts: bool = True, per_section: int = PER_SECTION
) -> SearchResults:
    """Search every section available. Empty ``q`` returns empty results.

    ``include_drafts`` follows the same rule as the article listing: only an
    editor sees work that is not published yet.
    """
    results = SearchResults(query=q)
    # Where each section's "see all" goes. Set here rather than at the end so
    # the shape is the same on the empty-query path. Both are "" without
    # pagebuilder, and the screen renders no link for an empty one.
    results.pages_more_url = pagebuilder.page_search_path(q.strip())
    results.media_more_url = pagebuilder.media_library_path()
    if not q.strip():
        return results

    pattern = like_pattern(q)
    await _search_articles(
        db, results, q, pattern, include_drafts=include_drafts, per_section=per_section
    )

    # ── Pages (only where pagebuilder is installed) ───────────────────
    pages, results.page_total = await pagebuilder.search_pages(
        db, pattern, include_drafts=include_drafts, limit=per_section
    )
    for page in pages:
        results.pages.append(
            SearchHit(
                id=page.id or 0,
                title=page.title,
                subtitle=f"{page.slug} · {page.status.value}",
                url=pagebuilder.page_editor_path(page.id or 0),
                excerpt=excerpt(page.draft_data, q),
            )
        )

    # ── Media (likewise) ──────────────────────────────────────────────
    assets, results.media_total = await pagebuilder.search_media(
        db, pattern, limit=per_section
    )
    for asset in assets:
        results.media.append(
            SearchHit(
                id=asset.id or 0,
                title=asset.original_filename,
                subtitle=asset.content_type,
                url=pagebuilder.media_library_path(),
                excerpt="",
            )
        )

    return results
