"""Deriving an article's address from its headline.

Its own module because the rule has to stay stable forever: a slug that shifts
under an existing article silently breaks every link already in the wild.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from news.constants import MAX_SLUG_ATTEMPTS, MAX_SLUG_LEN
from news.models import NewsArticle
from news.slugify import slugify


def slug_for_title(title: str) -> str:
    """News' own slug rule, bounded by the ``slug`` column.

    ``news.slugify`` already produces something ``SLUG_PATTERN`` accepts — it
    trims again after truncating, so the cut cannot leave a trailing hyphen —
    and falls back rather than returning an empty string. Both matter here: a
    slug that fails that pattern is a 422 the author has no way to act on.
    """
    return slugify(title, max_length=MAX_SLUG_LEN)


def _stem_length(base: str) -> int:
    """How much of ``base`` every candidate is guaranteed to share.

    The longest suffix is the one that eats the most of the base, so cutting to
    that leaves a prefix common to ``base`` and to all of its variants.
    """
    longest = len(str(MAX_SLUG_ATTEMPTS + 1))
    return min(len(base), MAX_SLUG_LEN - longest - 1)


async def free_slug(db: AsyncSession, base: str) -> str:
    """``base``, or ``base-2``, ``base-3``… — the first nobody is using.

    One query rather than one per candidate: the alternative is a
    create-and-catch-409 loop, and a failed insert rolls the session back, which
    would discard anything the caller had already written in the same
    transaction.

    Trashed articles are included in what counts as taken. Their slugs stay
    claimed — releasing one would let a new article take the URL, and restoring
    the old one would then collide or silently steal the address back.

    Returns ``""`` when even the suffixed candidates are all taken, which the
    caller turns into an error rather than guessing further.
    """
    # The prefilter is the *stem* rather than ``base``: a base already at
    # MAX_SLUG_LEN has to be cut to make room for the suffix, so its candidates
    # do not start with ``base`` and a ``startswith(base)`` filter would never
    # see them — handing back a candidate that is in fact taken.
    stem = base[: _stem_length(base)]
    taken = set(
        (
            await db.execute(
                select(NewsArticle.slug).where(NewsArticle.slug.startswith(stem))
            )
        ).scalars()
    )
    if base not in taken:
        return base
    for suffix in range(2, MAX_SLUG_ATTEMPTS + 2):
        candidate = f"{base[: MAX_SLUG_LEN - len(str(suffix)) - 1]}-{suffix}"
        if candidate not in taken:
            return candidate
    return ""


def slug_exhausted(title: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=f"Could not derive a free URL from {title!r}. Set one explicitly.",
    )


def slug_taken() -> HTTPException:
    """The conflict an author-supplied slug meets.

    Reported rather than silently altered: the URL is a thing they typed and
    expect to get.
    """
    return HTTPException(status_code=409, detail="Slug already in use")
