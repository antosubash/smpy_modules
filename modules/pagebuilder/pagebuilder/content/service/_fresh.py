"""Check an editor's base while holding the page until its transaction ends."""

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.content.service._common import _normalize_to_utc
from pagebuilder.contracts.schemas import PageVersionRequest
from pagebuilder.core.errors import PageConflict
from pagebuilder.models import NOT_TRASHED, Page


async def ensure_fresh_for_write(
    db: AsyncSession, page_id: int, body: PageVersionRequest | None
) -> None:
    # Null is the untouched page's version. Only absence opts out, preserving
    # existing API consumers and bundles without weakening the first save.
    if body is None or "expected_updated_at" not in body.model_fields_set:
        return
    # SQLite ignores FOR UPDATE. A no-op UPDATE locks on both SQLite and
    # Postgres, without changing the token if this request is refused.
    result = await db.execute(
        update(Page)
        .where(Page.id == page_id, NOT_TRASHED)
        .values(updated_at=Page.updated_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=404, detail="Page not found")
    # A writer that waited for the lock may already hold an older identity-map
    # copy. Reload after acquiring it, before comparing or mutating any fields.
    page = await db.get(Page, page_id, populate_existing=True)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    if _normalize_to_utc(body.expected_updated_at) != _normalize_to_utc(page.updated_at):
        raise PageConflict()
