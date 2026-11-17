"""Display names for calendar owners, resolved in one directory call."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import Request
from simple_module_core.user_directory import NullUserDirectory, get_user_directory

from sm_events.web.services.masking import label_carries_address
from sm_events.web.services.members import members_only

__all__ = ["owner_names"]


async def owner_names(request: Request, db: Any, owner_ids: Iterable[str]) -> dict[str, str | None]:
    """``{owner id: name or None}`` for the distinct *owner_ids*.

    One batch lookup, never one per row. The name follows the share picker's
    disclosure rule's stricter half: every viewer of a calendar sees this name,
    not only the owner and managers who may use the picker, so a label that
    carries an address resolves to ``None`` (never the address, masked or not).
    The same membership filter as the picker applies, in one batch: an account
    that is not (or no longer) a member of the bound tenant, a missing or inactive
    account, or no directory at all, is ``None``
    (the console words it neutrally)."""
    ids = sorted(set(owner_ids))
    names: dict[str, str | None] = dict.fromkeys(ids)
    directory = get_user_directory(request.app)
    if not ids or isinstance(directory, NullUserDirectory):
        return names
    found = [
        u for u in (await directory.get_many(db, ids)).values() if u.is_active and u.id in names
    ]
    for user in await members_only(request, db, found):
        if not label_carries_address(user.label, user.email):
            names[user.id] = user.label or None
    return names
