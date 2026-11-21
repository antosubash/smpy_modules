"""Slugs: ``[a-z0-9-]``, 1-80 characters, unique per tenant."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError

from sm_events.core import constants
from sm_events.core.errors import SlugTaken
from sm_events.models import EventText
from sm_events.models._base import Base

__all__ = ["free_slug", "free_text_slug", "slug_taken", "slug_write", "slugify", "text_slug_taken"]

_NOT_SLUG = re.compile(r"[^a-z0-9]+")


@asynccontextmanager
async def slug_write(db: Any, constraint: str) -> AsyncIterator[None]:
    """Start the savepoint before dirtying rows: ``begin_nested`` flushes first."""
    try:
        async with db.begin_nested():
            yield
            await db.flush()
    except IntegrityError as exc:
        if not _is_slug_conflict(exc, constraint):
            raise
        raise SlugTaken from exc


_UNIQUE_VIOLATION = "23505"


def _is_slug_conflict(exc: IntegrityError, constraint: str) -> bool:
    """Postgres: sqlstate ``23505`` on the expected constraint, read from the
    driver's error (SQLAlchemy's asyncpg adapter raises its own as ``orig`` and
    chains asyncpg's as ``__cause__``), never from message text, which the
    server may localise. SQLite has no such fields: the full message is compared."""
    orig = exc.orig
    chain = [orig, getattr(orig, "__cause__", None)]
    if any(
        getattr(e, "sqlstate", None) == _UNIQUE_VIOLATION
        and getattr(e, "constraint_name", None) == constraint
        for e in chain
        if e is not None
    ):
        return True
    return str(orig) == _sqlite_message(constraint)


@lru_cache(maxsize=16)
def _sqlite_message(constraint: str) -> str | None:
    """SQLite's text for a violation of ``constraint``, built from the model's
    own column list so it holds for any unique constraint (``tenant_id, slug``
    or ``tenant_id, locale, slug``); ``None`` for a name no table declares."""
    for table in Base.metadata.tables.values():
        for found in table.constraints:
            if isinstance(found, UniqueConstraint) and found.name == constraint:
                columns = ", ".join(f"{table.name}.{col.name}" for col in found.columns)
                return f"UNIQUE constraint failed: {columns}"
    return None


def slugify(text: str, fallback: str = constants.CALENDAR_SLUG_FALLBACK) -> str:
    """A slug from a display name: accents folded, everything else a hyphen.
    A name with nothing slug-able (emoji, right-to-left text) gets *fallback*,
    which each model names for itself."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    slug = _NOT_SLUG.sub("-", folded).strip("-")[: constants.SLUG_MAX].strip("-")
    return slug or fallback


async def slug_taken(db: Any, model: type, slug: str, *, except_id: Any = None) -> bool:
    """Is ``slug`` used in the bound tenant? Trashed rows keep their slug (the
    unique index covers them), so they count."""
    stmt = select(func.count()).select_from(model).where(model.slug == slug)  # type: ignore[attr-defined]
    if except_id is not None:
        stmt = stmt.where(model.id != except_id)  # type: ignore[attr-defined]
    return bool((await db.execute(stmt.execution_options(include_deleted=True))).scalar_one())


async def free_slug(db: Any, model: type, base: str) -> str:
    """``base``, else ``base-2``, ``base-3``... the first one nobody holds."""
    slug, n = base, 1
    while await slug_taken(db, model, slug):
        n += 1
        suffix = f"-{n}"
        slug = f"{base[: constants.SLUG_MAX - len(suffix)].rstrip('-')}{suffix}"
    return slug


async def text_slug_taken(db: Any, locale: str, slug: str, *, except_event: Any = None) -> bool:
    """Is ``slug`` used by an event text in ``locale``? Texts are never
    soft-deleted, so a trashed event's slug stays held (the index covers it)."""
    stmt = (
        select(func.count())
        .select_from(EventText)
        .where(EventText.locale == locale, EventText.slug == slug)
    )
    if except_event is not None:
        stmt = stmt.where(EventText.event_id != except_event)
    return bool((await db.execute(stmt)).scalar_one())


async def free_text_slug(db: Any, locale: str, base: str, *, except_event: Any = None) -> str:
    """``free_slug`` scoped to one language: ``base``, ``base-2``... the first
    one no other event's text holds in ``locale``."""
    slug, n = base, 1
    while await text_slug_taken(db, locale, slug, except_event=except_event):
        n += 1
        suffix = f"-{n}"
        slug = f"{base[: constants.SLUG_MAX - len(suffix)].rstrip('-')}{suffix}"
    return slug
