"""Slugs: ``[a-z0-9-]``, 1-80 characters, unique per tenant."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from sm_events.core import constants
from sm_events.core.errors import SlugTaken

__all__ = ["free_slug", "slug_taken", "slug_write", "slugify"]

_NOT_SLUG = re.compile(r"[^a-z0-9]+")


@asynccontextmanager
async def slug_write(db: Any, constraint: str) -> AsyncIterator[None]:
    """Start the savepoint before dirtying rows: ``begin_nested`` flushes first."""
    try:
        async with db.begin_nested():
            yield
            await db.flush()
    except IntegrityError as exc:
        message = str(exc.orig)
        # SQLite names the columns, Postgres names the unique constraint.
        table = constraint.removeprefix("uq_").removesuffix("_tenant_slug")
        sqlite_unique = f"UNIQUE constraint failed: {table}.tenant_id, {table}.slug"
        if f'unique constraint "{constraint}"' not in message and message != sqlite_unique:
            raise
        raise SlugTaken from exc


def slugify(text: str) -> str:
    """A slug from a display name: accents folded, everything else a hyphen."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    slug = _NOT_SLUG.sub("-", folded).strip("-")[: constants.SLUG_MAX].strip("-")
    return slug or constants.SLUG_FALLBACK


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
