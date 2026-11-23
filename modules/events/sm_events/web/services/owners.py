"""Display names for calendar owners: the member-name lookup, for a calendar's owner."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import Request

from sm_events.web.services.names import member_names

__all__ = ["owner_names"]


async def owner_names(request: Request, db: Any, owner_ids: Iterable[str]) -> dict[str, str | None]:
    """``{owner id: name or None}`` for the distinct *owner_ids*; see :func:`member_names`
    for the disclosure rule, the membership filter and the failure behaviour."""
    return await member_names(request, db, owner_ids)
