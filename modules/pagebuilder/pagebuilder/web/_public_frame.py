"""The site frame shared by public pages and cross-module readers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.content import site_nav
from pagebuilder.content.layout_service import LayoutService, public_layout_props
from pagebuilder.content.site_nav import SiteNav
from pagebuilder.core.settings import PagebuilderSettings
from pagebuilder.models import Layout
from pagebuilder.web.public_copy import public_copy


async def public_frame(
    db: AsyncSession | None,
    settings: PagebuilderSettings,
    locale: str,
    *,
    layout: Layout | None = None,
    nav: SiteNav | None = None,
) -> dict[str, Any]:
    """Read under the caller's tenant; reuse the viewer's ETag inputs when supplied.

    No database means no tenant's frame and no queries. Never commit: an empty
    site's layout is created within the caller's transaction.
    """
    if db is not None:
        if layout is None:
            layout = await LayoutService(db).get()
        if nav is None:
            nav = await site_nav.site_nav(db, settings.public_route_prefix, locale)
    return {
        **(
            public_layout_props(layout)
            if layout is not None
            else {"layout_header": None, "layout_footer": None}
        ),
        "site_nav": nav,
        "copy": public_copy(locale),
    }
