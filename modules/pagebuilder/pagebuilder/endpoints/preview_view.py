"""The admin's draft preview: the public page component, with a draft bar.

Split out of ``views.py`` (300-line cap). Included into ``views.router`` at the
place the route always had, so its URL and dependencies are unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_inertia import InertiaResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder import site_nav
from pagebuilder.deps import get_settings
from pagebuilder.layout_service import LayoutService, public_layout_props
from pagebuilder.og_image import og_image
from pagebuilder.public_copy import public_copy
from pagebuilder.service import PagesService
from pagebuilder.settings import PagebuilderSettings

router = APIRouter()

# The draft preview deliberately reuses the public component — see admin_preview.
_PAGE_PUBLIC = "PageBuilder/PublicPage"


@router.get("/{page_id}/preview", response_model=None)
async def admin_preview(
    page_id: int,
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
    settings: PagebuilderSettings = Depends(get_settings),
) -> InertiaResponse:
    """The draft as a visitor would see it.

    Rendered through the *public* page component rather than a preview-only
    one: a preview built from a second renderer is a preview that can disagree
    with the published page, which makes it worse than no preview at all.

    It reads ``draft_data``, so it answers the question the published URL
    cannot — what the unsaved-to-live version looks like. This is an admin
    route and stays behind the session, and it is marked noindex whatever the
    page's own setting says, because a preview URL that gets indexed in place
    of the real one is the one failure here that would be hard to undo.

    ``preview`` is what tells the component to show the draft bar (#89): a
    preview that looks exactly like the live page gets screenshotted and
    shared as if it were. Only this route sets it, so the public URL never
    shows the bar.
    """
    page = await PagesService(db).get_page(page_id)
    layout = await LayoutService(db).get()
    return await inertia.render(
        _PAGE_PUBLIC,
        {
            "title": (page.meta_title or "").strip() or page.title,
            "data": page.draft_data or {},
            "meta_description": page.meta_description,
            # Relative is fine here: a preview is noindex and never shared.
            "og_image": og_image(page.og_image, page.draft_data, ""),
            "canonical_url": None,
            "og_url": None,
            "index_in_search": False,
            "json_ld": page.json_ld,
            "site_name": settings.site_name,
            "twitter_handle": settings.twitter_handle,
            # No alternates: a preview is one draft, and advertising the
            # published translations of it from behind the session would name
            # live URLs on a page that is deliberately noindex.
            "locale": page.locale,
            "copy": public_copy(page.locale),
            **public_layout_props(layout),
            "site_nav": await site_nav.site_nav(db, settings.public_route_prefix, page.locale),
            "preview": {
                # The editor sits beside this route, under whatever prefix the
                # admin views are mounted at. Not `url_for("admin_edit")`:
                # route names are app-wide, and another module may share it.
                "editor_href": f"{request.url.path.removesuffix('/preview')}/edit",
                "status": page.status.value,
            },
        },
    )
