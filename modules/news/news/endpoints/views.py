"""Inertia view endpoints for News."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_hosting.permissions import RequiresPermission
from simple_module_inertia import InertiaResponse
from sqlalchemy.ext.asyncio import AsyncSession

from news import constants, locales
from news.content import ArticlesService
from news.endpoints.api._deps import may_see_drafts
from news.endpoints.public._render import render_article
from news.models import ArticleStatus, NewsArticle
from news.settings import active, public_article_path
from news.tenancy import bind_admin

router = APIRouter(dependencies=[Depends(bind_admin)])


def _locale_props() -> dict:
    """The site's content languages, for every screen that offers a choice.

    Inertia props rather than a fetch: these screens already load their rows
    client-side, and a second round trip for a list that never changes within a
    session would make the language filter appear a beat after the list it
    filters.

    Read from :mod:`news.locales`, which is news' own vocabulary: borrowed off
    the neighbour where pagebuilder is installed, and a single default where it
    is not. Never fetched from that module's ``/locales`` endpoint by the
    browser — the frontend reaching into a neighbour's API is exactly what
    ``news.integrations.pagebuilder`` exists to prevent — it is how the CSRF
    cookie name and the page API route ended up hardcoded in TSX before.
    """
    return {"locales": list(locales.supported()), "default_locale": locales.default()}


admin_router = APIRouter(dependencies=[Depends(bind_admin)])
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
    "/trash",
    response_model=None,
    dependencies=[Depends(RequiresPermission(constants.PERM_EDIT))],
)
async def article_trash(inertia: InertiaDep) -> InertiaResponse:
    """Articles that were binned, and the two things you can do with them.

    Trash, restore and purge were implemented and tested from the start and had
    no screen, so the admin list offered a hard delete instead — the one action
    the soft delete existed to avoid.
    """
    return await inertia.render(constants._PAGE_TRASH)


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

    The body has a canvas of its own next door, because the two are edited in
    genuinely different postures: this screen is a form full of short fields
    that each save independently, and that one is a full-bleed editor. Splitting
    them is what keeps either from being cramped by the other.

    Only the id is rendered; the article itself is fetched client-side, because
    every field on this screen saves independently and a full Inertia round trip
    per keystroke would be absurd.
    """
    return await inertia.render(
        constants._PAGE_ARTICLE_EDITOR,
        {
            "article_id": article_id,
            # Served rather than assembled in the browser, for the same reason
            # ``edit_url`` is on the listing DTO: this screen holds no opinion
            # about how the module routes its own screens.
            "preview_url": constants.ARTICLE_PREVIEW_URL.format(
                article_id=article_id
            ),
            **_locale_props(),
        },
    )


@router.get(
    "/articles/{article_id}/body",
    response_model=None,
    dependencies=[Depends(RequiresPermission(constants.PERM_EDIT))],
)
async def article_body(article_id: int, inertia: InertiaDep) -> InertiaResponse:
    """The block canvas an article's body is composed in.

    This route is the visible half of the split: it used to be a pagebuilder
    URL, because the body lived on one of its pages, and news linked out to it.
    News owns the document now, so it owns the canvas.

    The id alone again — the body is fetched client-side and autosaved, so
    rendering it through Inertia would only mean shipping the whole block
    document twice on every load.
    """
    return await inertia.render(
        constants._PAGE_ARTICLE_BODY, {"article_id": article_id}
    )


def _may_preview(request: Request) -> None:
    """``news.edit``, refused as a 404 rather than as a 403.

    ``news.edit`` and not ``news.publish``, deliberately. An author checking
    their own draft and a reviewer checking a submission both hold the former;
    gating on the latter would put the preview behind the very permission the
    reviewer is deciding whether to exercise, which is backwards.

    The refusal is a 404 because the public viewer's is: a draft, a trashed
    article and a slug that was never an article all answer the same there, and
    a 403 here would answer exactly the question that 404 exists to refuse —
    "does this article exist?" — to any caller who can guess an id.

    Reuses the API's ``may_see_drafts`` rather than ``RequiresPermission``,
    which raises 401/403 and cannot be talked out of it. That helper is also
    already the module's single definition of who may see an unpublished
    article, and this is the same question asked about a different surface.
    """
    if not may_see_drafts(request):
        raise HTTPException(status_code=404, detail="Article not found")


def _preview_state(article: NewsArticle) -> dict[str, Any]:
    """What the banner needs to say which document this is.

    ``live`` is the viewer's own rule — published *and* holding a snapshot —
    rather than an approximation of it, because both things it decides are
    about the public URL: whether to offer a link there at all, and whether
    "readers are still seeing something else" is even a true sentence.

    Which is why ``has_unpublished_changes`` is anded with it. An article can
    be a draft *and* hold a published snapshot, from before it was taken down,
    and a diverged draft in that state means nothing to a reader — there is
    nothing live to diverge from. Compared rather than inferred from a
    timestamp, too: an autosave that restored the previous text moves
    ``updated_at`` and leaves the document identical.
    """
    live = (
        article.status is ArticleStatus.PUBLISHED and article.published_data is not None
    )
    return {
        "status": article.status.value,
        "has_unpublished_changes": live
        and article.draft_data != article.published_data,
        "live_url": (
            public_article_path(article.slug, article.locale) if live else None
        ),
        "editor_url": constants.ARTICLE_EDITOR_URL.format(article_id=article.id),
    }


@router.get(
    "/articles/{article_id}/preview",
    response_model=None,
    dependencies=[Depends(_may_preview)],
)
async def article_preview(
    article_id: int,
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The article as a reader would see it, built from ``draft_data``.

    The gap this closes is in the workflow: ``approve`` publishes in a single
    action, so without this a reviewer commits an article to readers having
    seen only the block canvas — an editor, with drag handles and editor chrome,
    which is not the article. The public viewer cannot be asked instead, and
    must not be taught to: it serves published rows only, and that rule is what
    keeps a draft from leaking to anyone who guesses a slug.

    So this renders the *same screen* the reader gets — ``PublicArticle``, via
    ``_render`` — over the draft body, and marks it unmistakably as a preview.
    A second viewer would have been worthless the moment the two diverged.

    Addressed by id, not by ``(locale, slug)``. That is what keeps it out of
    the locale story entirely: the article is rendered in its own language
    because its own row says so, and there is no per-locale router here that a
    German article could be requested through an English prefix on.
    """
    article = await ArticlesService(db).get_article(article_id)
    response = await render_article(
        inertia,
        article=article,
        data=article.draft_data or {},
        locale=article.locale,
        settings=active(),
        # No canonical link and no ``hreflang``: a permission-gated URL should
        # claim to be the canonical version of nothing, and every translation
        # it could advertise is an address it is not reachable at. See
        # ``_render``, which defaults both to empty for exactly this caller.
        index_in_search=False,
        preview=_preview_state(article),
    )
    # Never stored, never indexed, and labelled with the language it is in —
    # the same three things the public viewer says about a real article, minus
    # the permission to cache it anywhere.
    response.headers["Cache-Control"] = constants.PRIVATE_CACHE_CONTROL
    response.headers["Content-Language"] = article.locale
    response.headers["X-Robots-Tag"] = constants.NOINDEX_ROBOTS_TAG
    return response
