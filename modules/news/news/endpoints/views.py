"""Inertia view endpoints for News."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from inertia import InertiaResponse
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_hosting.permissions import RequiresPermission

from news import constants
from news.integrations.locales import content_locales, default_locale

router = APIRouter()


def _locale_props() -> dict:
    """The site's content languages, for every screen that offers a choice.

    Inertia props rather than a fetch: these screens already load their rows
    client-side, and a second round trip for a list that never changes within a
    session would make the language filter appear a beat after the list it
    filters.

    Served by news rather than read from pagebuilder's own ``/locales``
    endpoint, even though that is where the value comes from. The frontend
    reaching into a neighbour's API is exactly what
    ``news.integrations.pagebuilder`` exists to prevent — it is how the CSRF
    cookie name and the page API route ended up hardcoded in TSX before.
    """
    return {"locales": list(content_locales()), "default_locale": default_locale()}


admin_router = APIRouter()
"""Routes mounted at the app root rather than under ``VIEW_PREFIX``.

The search screen spans articles, pages and media, so filing it under ``/news``
would misdescribe what it searches. Mounted in ``on_startup`` the same way
pagebuilder mounts its public viewer — routes are protected by default, so this
is behind the session like every other admin screen.
"""


@admin_router.get(
    "/search",
    response_model=None,
    dependencies=[Depends(RequiresPermission(constants.PERM_EDIT))],
)
async def admin_search(inertia: InertiaDep) -> InertiaResponse:
    """Search across articles, pages and media.

    Behind ``news.edit`` because it reaches into drafts and unpublished pages —
    the results are not the public site.
    """
    return await inertia.render(constants._PAGE_SEARCH)


@router.get(
    "/",
    response_model=None,
    dependencies=[Depends(RequiresPermission(constants.PERM_VIEW))],
)
async def article_list(inertia: InertiaDep) -> InertiaResponse:
    # The list is fetched client-side from /api/news/articles so an inline edit
    # can refresh one row without a full Inertia round trip.
    #
    # The page name comes from the constant, matching pagebuilder and this
    # repo's check_hardcoded_strings. The framework's own modules inline the
    # literal instead, for the SM003/SM004 static-AST pairing — the two
    # conventions disagree, and an in-repo module follows the in-repo linter.
    return await inertia.render(constants._PAGE_LIST, _locale_props())


@router.get(
    "/categories",
    response_model=None,
    dependencies=[Depends(RequiresPermission(constants.PERM_EDIT))],
)
async def category_list(inertia: InertiaDep) -> InertiaResponse:
    """Categories and tags.

    Behind ``news.edit`` rather than ``news.view``: everything on this screen is
    a write control, and the counts it shows include drafts.

    Like the article list, the data is fetched client-side — reordering and
    renaming both mutate several rows at once, and re-rendering the whole
    Inertia page after each would throw away the drag position.
    """
    return await inertia.render(constants._PAGE_CATEGORIES)


@router.get(
    "/articles/{article_id}/edit",
    response_model=None,
    dependencies=[Depends(RequiresPermission(constants.PERM_EDIT))],
)
async def article_editor(article_id: int, inertia: InertiaDep) -> InertiaResponse:
    """Everything about an article except its body.

    The body is a page-builder document and is edited in the page editor — an
    article *is* a page here, so duplicating that canvas would mean duplicating
    the block library, the autosave and the revision handling with it. This
    screen owns what the page has no concept of: category, tags, display date,
    byline and how the article behaves in feeds.

    Only the id is rendered; the article itself is fetched client-side, because
    every field on this screen saves independently and a full Inertia round trip
    per keystroke would be absurd.
    """
    return await inertia.render(
        constants._PAGE_ARTICLE_EDITOR,
        {"article_id": article_id, **_locale_props()},
    )
