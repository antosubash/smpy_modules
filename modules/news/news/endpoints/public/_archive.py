"""One archive page, however it was narrowed.

The index, a category, a tag, a byline and a search differ only in what they
filter by and what they call themselves. Everything else — the paging, the
canonical link, the ``hreflang`` set, the cache policy and the head — is the
same page, so it is written once here and the routes next door in ``_index``
supply the difference.

Split out of ``_index`` when the archive grew a search box and an author page:
the two files together were past the repo's 300-line cap, and the seam between
"what does this page filter by" and "how does an archive page render" was
already the one they were divided along internally.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode

from fastapi import HTTPException, Request, Response
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from news import constants, locales, service
from news.endpoints.public import _head
from news.endpoints.public._urls import absolute, listing_cache_control
from news.settings import NewsSettings, active, public_feed_path

PAGE_SIZE = 12
"""Articles per archive page.

Twelve rather than the API's default: this is a reading surface, and the number
that suits a JSON client fetching a sidebar is not the number that fills a page.
"""

MAX_QUERY_LEN = 100
"""How much of a search term is used.

Truncated rather than rejected. The term arrives from a query string on an
anonymous route, so a 422 for an over-long one would answer a reader with a
validation error on a page that has no way to show it — the same reasoning that
makes an unrecognised ``status`` filter ignored rather than refused. What is
kept is what the form echoes back and what the canonical link names, so the
page never claims to have searched for more than it did.
"""

SEARCH_ROBOTS = "noindex,follow"
"""What a search results page tells a crawler.

``noindex`` because the input space is unbounded: one indexed ``?q=`` link is an
invitation to enumerate query strings forever, and every result page is a
rearrangement of articles that are already indexed at their own addresses and
already reachable through the pager. ``follow`` rather than ``nofollow``
because the links out of it are the real documents — refusing to follow them
would be refusing the only useful thing on the page.
"""


def archive_url(path: str, *, page: int = 1, q: str = "") -> str:
    """An archive page's address, with whatever narrows it.

    The mirror of ``archiveUrl`` in ``news/utils/archiveUrl.ts``, and it has to
    stay one: this writes the canonical link and that builds the pager, so if
    the two spell the same page differently every paged search declares a
    canonical URL nothing on the site links to — a failure with no symptom
    anyone would notice for a year. Both sides are pinned to literal strings,
    here in ``test_public_search.py::test_the_canonical_names_the_search`` and
    there in ``archiveUrl.test.ts``.

    ``q`` before ``page`` so one page of one search has exactly one spelling;
    two orderings would be two URLs for one page.

    Page 1 carries no ``page`` parameter, for the reason
    ``settings.public_index_path`` gives: ``/news/`` and ``/news/?page=1``
    being two addresses is how an archive competes with itself in an index.
    """
    params: list[tuple[str, str]] = []
    if q:
        params.append(("q", q))
    if page > 1:
        params.append(("page", str(page)))
    return f"{path}?{urlencode(params)}" if params else path


def _archive_alternates(
    request: Request, settings: NewsSettings, path_for: Callable[[str], str]
) -> list[dict[str, str]]:
    """The same archive page in every other language.

    No query behind it, unlike an article's: an archive exists in each language
    by construction — every locale has an index, and a category or tag page for
    any slug — so the set of addresses is derivable rather than something to
    look up. Empty on a monolingual site, where a lone self-referential
    ``hreflang`` would be noise.
    """
    languages = locales.supported()
    if len(languages) < 2:
        return []
    entries = [
        {"locale": locale, "url": absolute(request, settings, path_for(locale))}
        for locale in languages
    ]
    default = next((e for e in entries if locales.is_default(e["locale"])), None)
    if default is not None:
        entries.append({"locale": "x-default", "url": default["url"]})
    return entries


async def render_archive(
    *,
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession,
    locale: str,
    page: int,
    path_for: Callable[[str], str],
    heading: str,
    description: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    authors: list[str] | None = None,
    q: str | None = None,
) -> Response:
    """Render one archive page.

    ``path_for`` builds this page's address in a given language rather than
    being handed a finished path, because the canonical link and the
    ``hreflang`` set are the same address in different languages and deriving
    one from the other is what keeps them from drifting.

    A search *narrows* whatever page it was typed on rather than replacing it:
    ``/news/category/field-notes?q=canopy`` searches within the category, and
    the filters compose by construction because they are separate arguments to
    one listing query. Narrowing is what the address already promises — the
    reader is standing on the category page — and a search that silently
    dropped that scope would answer a question nobody asked.
    """
    settings: NewsSettings = active()
    query = (q or "").strip()[:MAX_QUERY_LEN]
    path = path_for(locale)
    items, total = await service.list_articles(
        db,
        limit=PAGE_SIZE,
        offset=(page - 1) * PAGE_SIZE,
        category=category,
        tag=tag,
        authors=authors,
        q=query or None,
        locale=locale,
        # An archive lists what is published, and honours the same
        # "keep this out of feeds" flag the feed block does: an article held
        # back from listings should not reappear in the one listing that is the
        # site's front door. A search obeys it too — otherwise the archive's
        # visibility rule would have a search box for a back door.
        in_feed_only=True,
    )
    pages = max(1, -(-total // PAGE_SIZE))
    if page > pages:
        # Past the end is a 404 rather than an empty page, so a crawler that
        # guesses ?page=900 is told there is nothing there instead of being
        # handed a valid-looking empty document to index. True of an archive
        # with nothing in it as well: page 1 of an empty tag, byline or search
        # is a real address that happens to be empty, but there is no reading
        # under which it has a page 2.
        raise HTTPException(status_code=404, detail="No such page")

    canonical = absolute(request, settings, archive_url(path, page=page, q=query))
    feed_path = public_feed_path(locale)
    rendered = await inertia.render(
        constants._PAGE_PUBLIC_INDEX,
        {
            "heading": heading,
            "description": description,
            "items": [item.model_dump(mode="json") for item in items],
            "page": page,
            "pages": pages,
            "total": total,
            "base_path": path,
            "query": query,
            # Whether this page was already narrowed before any search — the
            # search box says "search in Field notes" rather than "search
            # articles", which is the difference between a box that scopes what
            # it says it scopes and one a reader has to guess about.
            "narrowed": bool(category or tag or authors is not None),
            "feed_url": feed_path,
            "site_name": settings.site_name or None,
            "locale": locale,
        },
    )
    response = _head.inject(
        rendered,
        _head.listing_head(
            title=(
                heading
                if not settings.site_name
                else f"{heading} — {settings.site_name}"
            ),
            description=description,
            canonical=canonical,
            site_name=settings.site_name or None,
            feed_url=absolute(request, settings, feed_path),
            locale=locale,
            # A search page advertises no translations. The others are the same
            # document in each language; a set of results for an English phrase
            # is not the German page's content, and pointing a crawler at it as
            # though it were would be a claim about a page that does not exist.
            alternates=(
                None if query else _archive_alternates(request, settings, path_for)
            ),
            robots=SEARCH_ROBOTS if query else None,
        ),
    )
    response.headers["Cache-Control"] = listing_cache_control(settings)
    response.headers["Content-Language"] = locale
    return response
