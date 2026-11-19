"""The one 404 of the public surface.

One answer for every cause (a slug that never existed, a draft, an in-review or scheduled
event, an event of an internal or private calendar, a trashed event or calendar, another
tenant's row, a text in another language, a skipped occurrence, a request that resolved no
tenant) so the response says nothing about which applied. Same status, same props, and,
through :class:`~sm_events.web.endpoints.public._errors.PublicErrorRoute`, the same
``no-store`` and tenant ``Vary`` with no ``ETag``.

Where pagebuilder is mounted it is the site's own 404, in the address's language. Without
it, events' own ``Events/PublicNotFound`` page: a message, a link to the index and the next
public occurrences, never derived from what was requested. A request that resolved no tenant
renders no layout and runs no query.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, Response
from simple_module_hosting.inertia_deps import InertiaDep

from sm_events.core import clock, constants, locales
from sm_events.integrations import pagebuilder
from sm_events.web.endpoints.public import _urls
from sm_events.web.endpoints.public._listing import upcoming

__all__ = ["not_found"]


async def _suggestions(db: Any, *, locale: str) -> list[dict[str, Any]]:
    """The next public occurrences to offer instead: the same for every cause and never derived
    from what was requested, so they say nothing about it."""
    items = await upcoming(
        db,
        locale=locale,
        default_locale=locales.default(),
        now=clock.now(),
        calendar_ids=None,
        category_id=None,
        window_days=constants.NOT_FOUND_WINDOW_DAYS,
        limit=constants.NOT_FOUND_SUGGESTIONS,
    )
    return [item.model_dump(mode="json") for item in items[: constants.NOT_FOUND_SUGGESTIONS]]


async def not_found(
    request: Request,
    inertia: InertiaDep,
    db: Any,
    *,
    locale: str,
    tenant: str | None,
) -> Response:
    """The 404 for ``request`` in ``locale``. ``tenant`` is what the request's binder
    answered; ``None`` queries nothing."""
    rendered = await pagebuilder.render_not_found(
        request,
        inertia,
        db,
        locale=locale,
        tenant_id=tenant,
        detail=constants.NOT_FOUND_DETAIL,
    )
    if rendered is not None:
        return rendered
    suggestions = [] if tenant is None else await _suggestions(db, locale=locale)
    response = await inertia.render(
        constants._PAGE_PUBLIC_NOT_FOUND,
        {
            "locale": locale,
            "index_url": _urls.index_path(locale),
            "suggestions": suggestions,
        },
    )
    response.status_code = 404
    return response
