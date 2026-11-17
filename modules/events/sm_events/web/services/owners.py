"""Display names for calendar owners, resolved in one directory call."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import Request
from simple_module_core.user_directory import NullUserDirectory, get_user_directory

from sm_events.web.services.masking import safe_display_name

__all__ = ["owner_names"]


async def owner_names(request: Request, db: Any, owner_ids: Iterable[str]) -> dict[str, str | None]:
    """``{owner id: name or None}`` for the distinct *owner_ids*.

    One batch lookup, never one per row. The name follows the share picker's
    disclosure rule: a label that carries an address is shown as the masked
    address. A missing or inactive account, or no directory at all, is ``None``
    (the console words it neutrally)."""
    ids = sorted(set(owner_ids))
    names: dict[str, str | None] = dict.fromkeys(ids)
    directory = get_user_directory(request.app)
    if not ids or isinstance(directory, NullUserDirectory):
        return names
    for uid, user in (await directory.get_many(db, ids)).items():
        if user.is_active and uid in names:
            names[uid] = safe_display_name(user.label, user.email, "") or None
    return names
