"""Tag management — freeform labels, many per article.

Tags differ from categories in every way that matters here: they are created
while writing rather than administered up front, they carry no ordering, and an
article has any number of them. What the screen needs is therefore a usage
count per tag and a way to fold near-duplicates together, not CRUD.
"""

from __future__ import annotations

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from news.constants import MAX_TAG_LEN
from news.contracts.schemas import TagRead
from news.models import NewsArticleTag, NewsTag
from news.slugify import slugify, unique_slug


async def list_tags(db: AsyncSession) -> list[TagRead]:
    """Every tag with its usage count, most-used first.

    An outer join, so a tag used nowhere still lists — those are exactly the
    rows the screen fades and offers to merge away.
    """
    rows = (
        await db.execute(
            select(NewsTag, func.count(NewsArticleTag.article_id))
            .outerjoin(NewsArticleTag, NewsArticleTag.tag_id == NewsTag.id)
            .group_by(NewsTag.id)
            .order_by(func.count(NewsArticleTag.article_id).desc(), NewsTag.name)
        )
    ).all()
    return [
        TagRead(id=tag.id or 0, name=tag.name, slug=tag.slug, article_count=int(count))
        for tag, count in rows
    ]


async def get(db: AsyncSession, tag_id: int) -> NewsTag | None:
    return await db.scalar(select(NewsTag).where(NewsTag.id == tag_id))


async def get_or_create(db: AsyncSession, name: str) -> NewsTag:
    """Find a tag by name, or make it.

    Matching is on the *slug*, not the name: "Urban", "urban" and "urban " are
    one tag to a writer, and letting them become three is how a tag list turns
    into noise. The first spelling wins as the display name.
    """
    slug = slugify(name, max_length=MAX_TAG_LEN)
    existing = await db.scalar(select(NewsTag).where(NewsTag.slug == slug))
    if existing is not None:
        return existing
    taken = set((await db.execute(select(NewsTag.slug))).scalars().all())
    tag = NewsTag(name=name.strip(), slug=unique_slug(name, taken, max_length=MAX_TAG_LEN))
    db.add(tag)
    await db.flush()
    await db.refresh(tag)
    return tag


async def list_for_article(db: AsyncSession, article_id: int) -> list[str]:
    """Tag names on one article, in display order."""
    rows = (
        await db.execute(
            select(NewsTag.name)
            .join(NewsArticleTag, NewsArticleTag.tag_id == NewsTag.id)
            .where(NewsArticleTag.article_id == article_id)
            .order_by(NewsTag.name)
        )
    ).scalars().all()
    return list(rows)


async def names_for_articles(
    db: AsyncSession, article_ids: list[int]
) -> dict[int, list[str]]:
    """Tags for many articles in one query.

    The list view needs tags per row; doing it per row is the classic N+1 that
    makes a 25-row page issue 26 queries.
    """
    if not article_ids:
        return {}
    rows = (
        await db.execute(
            select(NewsArticleTag.article_id, NewsTag.name)
            .join(NewsTag, NewsTag.id == NewsArticleTag.tag_id)
            .where(NewsArticleTag.article_id.in_(article_ids))
            .order_by(NewsTag.name)
        )
    ).all()
    out: dict[int, list[str]] = {}
    for article_id, name in rows:
        out.setdefault(article_id, []).append(name)
    return out


async def set_for_article(db: AsyncSession, article_id: int, names: list[str]) -> list[str]:
    """Replace an article's tags with ``names``, creating any that are new.

    Replace rather than merge: the editor sends the full set it is showing, so
    a tag the writer removed has to disappear. Returns the resulting names.
    """
    tags = []
    seen: set[int] = set()
    for name in names:
        if not name.strip():
            continue
        tag = await get_or_create(db, name)
        if tag.id in seen:
            continue
        seen.add(tag.id or 0)
        tags.append(tag)

    await db.execute(
        sa_delete(NewsArticleTag).where(NewsArticleTag.article_id == article_id)
    )
    for tag in tags:
        db.add(NewsArticleTag(article_id=article_id, tag_id=tag.id or 0))
    await db.flush()
    return sorted(tag.name for tag in tags)


async def rename(db: AsyncSession, tag: NewsTag, name: str) -> NewsTag:
    """Rename a tag in place. The slug follows, so links stay derivable."""
    taken = set(
        (await db.execute(select(NewsTag.slug).where(NewsTag.id != tag.id)))
        .scalars()
        .all()
    )
    tag.name = name.strip()
    tag.slug = unique_slug(name, taken, max_length=MAX_TAG_LEN)
    db.add(tag)
    await db.flush()
    await db.refresh(tag)
    return tag


async def merge(db: AsyncSession, *, source: NewsTag, target: NewsTag) -> int:
    """Fold ``source`` into ``target`` and delete it. Returns articles moved.

    Links are re-pointed one at a time past the ones the target already has,
    rather than with a bulk UPDATE: an article carrying *both* tags would
    otherwise collide on the composite primary key and abort the merge — which
    is precisely the case a merge exists to handle.
    """
    if source.id == target.id:
        return 0

    source_articles = set(
        (
            await db.execute(
                select(NewsArticleTag.article_id).where(
                    NewsArticleTag.tag_id == source.id
                )
            )
        )
        .scalars()
        .all()
    )
    target_articles = set(
        (
            await db.execute(
                select(NewsArticleTag.article_id).where(
                    NewsArticleTag.tag_id == target.id
                )
            )
        )
        .scalars()
        .all()
    )

    for article_id in sorted(source_articles - target_articles):
        db.add(NewsArticleTag(article_id=article_id, tag_id=target.id or 0))

    await db.execute(sa_delete(NewsArticleTag).where(NewsArticleTag.tag_id == source.id))
    await db.delete(source)
    await db.flush()
    return len(source_articles)
