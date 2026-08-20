"""Where an asset is actually used.

An asset is referenced by URL inside a page's block JSON, not by a foreign key,
so "is this in use" is a text question rather than a relational one. That is a
consequence of the block editor storing arbitrary props: a picture can be a
hero's background, an image block's src, or a URL someone typed into a rich-text
field, and no schema anticipates all three.

The answer matters because deleting an asset in use does not fail loudly — the
row goes, the file goes, and the pages that referenced it start serving a broken
image that nobody notices until someone looks.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.models import NOT_TRASHED, Page


@dataclass(frozen=True)
class Usage:
    """One page that references the asset."""

    page_id: int
    title: str
    slug: str
    status: str
    #: True when only the draft references it — the published page does not yet.
    draft_only: bool


def _like_literal(value: str) -> str:
    """Escape LIKE's wildcards so ``value`` is matched literally.

    Same rule as ``list_pages`` and ``board._search_filter``. It matters more
    here than in a search box: an uploaded filename almost always contains
    ``_``, which LIKE reads as "any single character", so ``hero_1.png`` would
    also match ``heroX1.png`` — and this query decides whether an asset is safe
    to delete. The failure is a spurious refusal, never a missed reference: a
    stray wildcard can only widen the match.
    """
    return value.translate(str.maketrans({"%": r"\%", "_": r"\_", "\\": "\\\\"}))


def _references(column, needle: str):
    """A LIKE against the block JSON cast to text.

    Evaluated in the database. Loading every page's blocks to scan them in
    Python is what made listings scale with content size rather than row count,
    and this question gets asked from the media library.

    The cast is explicit because SQLAlchemy compiles an untyped ``func.cast`` to
    NullType and the whole statement fails at compile time.
    """
    return cast(column, Text).like(f"%{_like_literal(needle)}%", escape="\\")


async def find(db: AsyncSession, url: str, *, limit: int = 20) -> tuple[list[Usage], int]:
    """Pages referencing ``url``. Returns (first ``limit``, total).

    Matching is on the URL rather than the filename: a filename like ``2.jpg``
    would match half the library by substring, while the URL is unique to the
    asset.

    Trashed pages do not count. They are invisible and offline, so an asset used
    only by one is, for the purposes of "can I delete this", unused — and
    blocking on a page nobody can see would be impossible to act on.
    """
    if not url:
        return [], 0

    matches = or_(
        _references(Page.draft_data, url),
        _references(Page.published_data, url),
    )
    base = select(Page).where(NOT_TRASHED, matches)

    total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (await db.execute(base.order_by(Page.id.desc()).limit(limit))).scalars().all()

    usages = []
    for page in rows:
        in_published = bool(
            page.published_data and url in str(page.published_data)
        )
        usages.append(
            Usage(
                page_id=page.id or 0,
                title=page.title,
                slug=page.slug,
                status=page.status.value,
                # Worth distinguishing: an asset referenced only by an unsaved
                # draft is a weaker claim than one that is live on the site.
                draft_only=not in_published,
            )
        )
    return usages, total
