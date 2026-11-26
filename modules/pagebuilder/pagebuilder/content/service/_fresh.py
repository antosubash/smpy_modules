"""Check an editor's base while holding the row until its transaction ends."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.content.service._common import _normalize_to_utc
from pagebuilder.core.errors import LayoutConflict, PageConflict, PageNotFound
from pagebuilder.models import NOT_TRASHED, Layout, Page

if TYPE_CHECKING:
    from pagebuilder.contracts.schemas._fields import VersionRequest


async def ensure_fresh_for_write(
    db: AsyncSession,
    row_id: int,
    body: VersionRequest | None,
    *,
    model: type[Page] | type[Layout] = Page,
) -> None:
    missing = PageNotFound() if model is Page else HTTPException(404, "Layout not found")
    # Null is the untouched row's version. Only absence opts out, preserving
    # existing API consumers and bundles without weakening the first save.
    if body is None or "expected_updated_at" not in body.model_fields_set:
        # Overwrite opts out of version checking, never out of page existence.
        row = await db.get(model, row_id, populate_existing=True)
        if row is None or (isinstance(row, Page) and row.deleted_at is not None):
            raise missing
        return
    # SQLite ignores FOR UPDATE. A no-op UPDATE locks on both SQLite and
    # Postgres, without changing the token if this request is refused.
    result = await db.execute(
        update(model)
        .where(model.id == row_id, *([NOT_TRASHED] if model is Page else []))
        .values(updated_at=model.updated_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise missing
    # A writer that waited for the lock may already hold an older identity-map
    # copy. Reload after acquiring it, before comparing or mutating any fields.
    row = await db.get(model, row_id, populate_existing=True)
    if row is None:
        raise missing
    if _normalize_to_utc(body.expected_updated_at) != _normalize_to_utc(row.updated_at):
        raise PageConflict() if model is Page else LayoutConflict()
