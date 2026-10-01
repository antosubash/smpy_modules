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
from news.slugify import tag_slug


class TagNameError(ValueError):
    """The name cannot become a tag (no letters or numbers)."""


class TagCollisionError(ValueError):
    """Another tag already uses this name or address."""


NO_ALNUM_MESSAGE = "A tag needs at least one letter or number."


def _slug_for(name: str) -> str:
    slug = tag_slug(name, max_length=MAX_TAG_LEN)
    if not slug:
        raise TagNameError(NO_ALNUM_MESSAGE)
    return slug


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
    slug = _slug_for(name)
    existing = await db.scalar(select(NewsTag).where(NewsTag.slug == slug))
    if existing is not None:
        return existing
    tag = NewsTag(name=name.strip(), slug=slug)
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
    name = name.strip()
    slug = _slug_for(name)
    clash = await db.scalar(
        select(NewsTag.id).where(
            NewsTag.id != tag.id,
            (NewsTag.slug == slug) | (func.lower(NewsTag.name) == name.lower()),
        )
    )
    if clash is not None:
        raise TagCollisionError(f"A tag named {name!r} already exists.")
    tag.name = name
    tag.slug = slug
    db.add(tag)
    await db.flush()
    await db.refresh(tag)
    return tag


async def delete(db: AsyncSession, tag: NewsTag) -> None:
    """Remove the tag and its links. The articles are untouched.

    The links are deleted explicitly even though ``NewsArticleTag`` declares
    ``ondelete="CASCADE"``: that is enforced by the database, and SQLite only
    enforces foreign keys when the connection has run ``PRAGMA
    foreign_keys=ON``, which nothing in this stack does. A surviving link is not
    inert — SQLite reuses ids, so it re-attaches to the next tag created and an
    article silently acquires a tag nobody applied.

    ``merge`` already does this for the same reason; this is the other path.
    """
    await db.execute(sa_delete(NewsArticleTag).where(NewsArticleTag.tag_id == tag.id))
    await db.delete(tag)
    await db.flush()


async def unlink_article(db: AsyncSession, article_id: int) -> None:
    """Drop every link belonging to an article that is going away.

    Same reasoning as :func:`delete`, from the other side of the join.
    """
    await db.execute(
        sa_delete(NewsArticleTag).where(NewsArticleTag.article_id == article_id)
    )


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
