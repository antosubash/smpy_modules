"""Listing and counting queries for media assets.

Split from :mod:`pagebuilder.media_service` so that module stays focused on
storage and uploads, and both files stay under the 300-line cap.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.models import MediaAsset

DEFAULT_PAGE_SIZE = 60
MAX_PAGE_SIZE = 200


def filtered_stmt(
    *,
    search: str | None = None,
    content_type: str | None = None,
    folder: str | None = None,
    unfiled_only: bool = False,
    min_size_bytes: int | None = None,
    max_size_bytes: int | None = None,
):
    """Build the SELECT shared by listing and counting."""
    stmt = select(MediaAsset)
    if search:
        # SQLite LIKE is case-insensitive for ASCII by default; this matches
        # what users expect ("hero" finds "Hero.jpg").
        stmt = stmt.where(MediaAsset.original_filename.like(f"%{search}%"))
    if content_type:
        if content_type.endswith("/*"):
            stmt = stmt.where(MediaAsset.content_type.like(f"{content_type[:-1]}%"))
        else:
            stmt = stmt.where(MediaAsset.content_type == content_type)
    if unfiled_only:
        stmt = stmt.where(MediaAsset.folder.is_(None))
    elif folder is not None:
        stmt = stmt.where(MediaAsset.folder == folder)
    if min_size_bytes is not None:
        stmt = stmt.where(MediaAsset.size_bytes >= min_size_bytes)
    if max_size_bytes is not None:
        stmt = stmt.where(MediaAsset.size_bytes <= max_size_bytes)
    return stmt


async def count_assets(db: AsyncSession, **filters) -> int:
    """Total rows matching *filters* — for offset-paginated callers."""
    inner = filtered_stmt(**filters).subquery()
    result = await db.execute(select(func.count()).select_from(inner))
    return int(result.scalar_one())


async def list_assets(
    db: AsyncSession,
    *,
    cursor: int | None = None,
    offset: int | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    **filters,
) -> tuple[list[MediaAsset], int | None]:
    """Return one page of assets newest-first, plus the next cursor.

    Two paging modes. The default is cursor-based: the cursor is the smallest
    ``id`` on the previous page, and the query asks for ``limit + 1`` rows so
    the end of the list is detectable without a separate count.

    Passing ``offset`` switches to offset paging, which the image-picker
    gallery needs because it jumps to arbitrary pages. ``next_cursor`` is then
    always ``None`` and callers pair it with :func:`count_assets`.
    """
    page_size = max(1, min(limit, MAX_PAGE_SIZE))
    stmt = filtered_stmt(**filters)

    if offset is not None:
        stmt = stmt.order_by(MediaAsset.id.desc()).offset(max(0, offset)).limit(page_size)
        result = await db.execute(stmt)
        return list(result.scalars().all()), None

    if cursor is not None:
        stmt = stmt.where(MediaAsset.id < cursor)
    stmt = stmt.order_by(MediaAsset.id.desc()).limit(page_size + 1)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    next_cursor: int | None = None
    if len(rows) > page_size:
        rows = rows[:page_size]
        next_cursor = rows[-1].id
    return rows, next_cursor
