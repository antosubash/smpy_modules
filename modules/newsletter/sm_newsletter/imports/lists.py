"""Creating the list an import lands in: records' contract, newsletter's errors."""

from __future__ import annotations

from typing import Any

from simple_module_db.listeners import current_user_id
from sm_records.contracts import newsletter_import as records
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import errors_import

__all__ = ["create_list"]


async def create_list(
    app: Any, session: AsyncSession, *, tenant_id: str, key: str, label: str
) -> str:
    """The key of a new list (double opt-in, not yet open for public signup).

    :class:`~sm_newsletter.core.errors_import.ListExists` when the key is taken,
    :class:`~sm_newsletter.core.errors_import.InvalidListKey` when records refuses it."""
    try:
        return await records.create_list(
            session,
            tenant_id=tenant_id,
            key=key,
            label=label,
            app=app,
            actor=current_user_id.get(),
        )
    except records.ListExists:
        raise errors_import.ListExists() from None
    except records.InvalidListKey:
        raise errors_import.InvalidListKey() from None
