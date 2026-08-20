"""Shared dependencies for the News API.

Split out of the endpoint modules so the draft-visibility rule has exactly one
definition. It is subtle enough (see ``_may_see_drafts``) that a second copy
would drift.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from simple_module_hosting.permissions import (
    WILDCARD,
    RequiresPermission,
    resolve_permissions,
)
from sqlalchemy.ext.asyncio import AsyncSession

from news import service
from news.constants import PERM_EDIT
from news.contracts.schemas import ArticleRead

require_edit = Depends(RequiresPermission(PERM_EDIT))


def may_see_drafts(request: Request) -> bool:
    """Only an editor sees articles whose page is still a draft.

    Everyone else gets the published site, which is what the public feed block
    must show.

    Reads ``request.state.resolved_permissions`` — where the hosting middleware
    and ``RequiresPermission`` both put the resolved set — rather than a
    ``permissions`` attribute on the user. ``UserContext`` has no such
    attribute, so testing it always yielded an empty list and no editor ever
    saw a draft.

    The fallback mirrors ``RequiresPermission.__call__``: these listings are
    registered as public routes, so on an anonymous-readable GET nothing has
    populated ``resolved_permissions`` by the time we are asked. ``WILDCARD`` is
    checked because an administrator resolves to it rather than to a literal
    ``news.edit``.
    """
    resolved = getattr(request.state, "resolved_permissions", None)
    if resolved is None:
        user = getattr(request.state, "user", None)
        if user is None:
            return False
        sm = getattr(getattr(request.app, "state", None), "sm", None)
        registry = getattr(sm, "permissions", None) if sm is not None else None
        resolved = resolve_permissions(
            getattr(user, "roles", None) or [],
            role_map=registry.role_map if registry is not None else None,
        )
    return WILDCARD in resolved or PERM_EDIT in resolved



async def read_one_by_page(db: AsyncSession, page_id: int) -> ArticleRead:
    """Re-read through the listing join so every response has one shape.

    Drafts are included: an editor has just written this row and must see it
    back whatever state its page is in.
    """
    article = await service.get_read_by_page(db, page_id, include_drafts=True)
    if article is None:
        # The page is the only source of slug and title, so without it there is
        # nothing to return.
        raise HTTPException(status_code=404, detail="Article's page not found.")
    return article
