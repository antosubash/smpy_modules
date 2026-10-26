"""What a reader gets for an article, or an archive page, that is not there (#248).

One answer for every cause — a slug that was never an article, a draft, a
trashed article, one scheduled but not yet live, a request that resolved no
tenant — so the response says nothing about which applied.

Where pagebuilder is mounted it is the site's own 404, through
:func:`news.integrations.pagebuilder.render_not_found`: the tenant's header,
footer, branding and design pack, in the address's language, ``no-store``. A
reader who followed a dead article link is still on the same site. Without
pagebuilder there is no site frame to put it in, so the host's error page
answers, with the same cache headers.
"""

from __future__ import annotations

from typing import Final, NoReturn

from fastapi import HTTPException, Request, Response
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from news import tenancy
from news.integrations import pagebuilder

ARTICLE_NOT_FOUND: Final = "Article not found"
"""The JSON detail for a missing article, word for word what it always was."""

NO_SUCH_PAGE: Final = "No such page"
"""The JSON detail for an archive page past the end."""

NO_STORE: Final = "no-store"
"""Never kept anywhere: a cached "missing" would hide an article published a
second later, and a shared cache holding one tenant's 404 could answer
another tenant's address with it."""


async def not_found(
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession,
    *,
    locale: str,
    tenant: str | None,
    detail: str = ARTICLE_NOT_FOUND,
) -> Response:
    """The 404 for ``request``, in ``locale``. ``tenant`` ``None`` renders no layout."""
    rendered = await pagebuilder.render_not_found(
        request, inertia, db, locale=locale, tenant_id=tenant, detail=detail
    )
    if rendered is None:
        _raise(request, detail)
    return rendered


def _raise(request: Request, detail: str) -> NoReturn:
    headers = Response()
    headers.headers["Cache-Control"] = NO_STORE
    tenancy.vary_on_tenant(headers, request)
    raise HTTPException(
        status_code=404,
        detail=detail,
        headers={k: v for k, v in headers.headers.items() if k != "content-length"},
    )
