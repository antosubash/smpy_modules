"""``/feed/{token}.ics``: one calendar, as one user may see it now.

**The module's third documented tenancy exception**, after newsletter's ``/newsletter/u/{token}``
and records' form token. The token is the capability, so the tenant comes from the token's row
(one narrow cross-tenant read by digest), never from the request: a visitor's session or header
tenant is left (``no_tenant``) and only a tenant the *host* resolved can refuse the link
(:func:`~sm_events.web.endpoints.public._host_tenant.host_tenant`). So this router is **not**
under ``public_tenant`` or ``bind_public``, and it has no dependencies at all.

**One answer for "no".** A malformed, unknown, revoked or expired link, an account that is gone,
inactive or no longer a member, roles nobody can read, a lost ``events.view``, a removed share, a
narrowed visibility, a trashed calendar and a host that contradicts the link all reach the single
:func:`deny`, held back to ``FEED_DENY_FLOOR_SECONDS`` after the handler started so the extra
work some of them did is not observable. The only other shapes are the per-token ``429``, which
is decided from the presented string before anything is read, and a ``503`` for an internal
failure, which says nothing about the token. A malformed token skips the database. A check
that *fails* (the directory, the membership store or a grant source raising) after the link's
row was found is that same refusal, so an outage is no oracle; the 503 is for failures
independent of the token (the database itself).

**Never cached, never validated**: ``private, no-store``, no ``ETag``, no ``304``, no
``Content-Disposition`` (a subscription opens inline), ``Referrer-Policy: no-referrer``. ``HEAD``
is ``GET`` without the body. The handler logs nothing that names the token: failures by class
name only (an exception's text can carry the path), and the log filter
(:mod:`sm_events.feeds.tokens.log_redact`) scrubs the framework's own request lines.

What a link serves is :meth:`FeedAccess.events`: the **published** events of its calendar that
its owner may see at this moment.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time

from fastapi import APIRouter, Request, Response
from simple_module_db import no_tenant

from sm_events.calendar.plugins.extension_types import SourceViewer
from sm_events.core import constants, locales, timezones
from sm_events.core.access.offline import feed_viewer
from sm_events.core.tenancy import tenant_scope, valid_tenant
from sm_events.feeds.select import feed_events
from sm_events.feeds.tokens.codec import well_formed
from sm_events.feeds.tokens.resolve import FeedAccess, TokenRow, lookup, resolve, touch_last_used
from sm_events.feeds.tokens.throttle import TokenThrottle
from sm_events.web.endpoints.public import _clock, _urls
from sm_events.web.endpoints.public._feeds import TRUNCATED_HEADER, ics_file, plugin_events
from sm_events.web.endpoints.public._host_tenant import host_tenant

__all__ = ["THROTTLE", "deny", "private_feed", "router"]

_log = logging.getLogger("sm_events.private_feed")
_METHODS = sorted(constants.PUBLIC_METHODS)

THROTTLE = TokenThrottle(
    limit=constants.FEED_TOKEN_RATE,
    window=constants.FEED_TOKEN_WINDOW_SECONDS,
    max_keys=constants.FEED_THROTTLE_KEYS,
)

router = APIRouter()


def _headers(cache: str = constants.PRIVATE_FEED_NO_STORE, **extra: str) -> dict[str, str]:
    """What every answer of this route carries: never stored, never referring, never indexed."""
    return {
        "Cache-Control": cache,
        "Referrer-Policy": constants.NO_REFERRER,
        "X-Robots-Tag": constants.NO_INDEX,
        **extra,
    }


def _answer(
    request: Request,
    body: bytes,
    status: int,
    media_type: str,
    headers: dict[str, str],
) -> Response:
    """``body`` as ``GET`` answers it; ``HEAD`` gets the same headers and no body."""
    head = request.method == "HEAD"
    response = Response(
        b"" if head else body, status_code=status, media_type=media_type, headers=headers
    )
    if head:
        response.headers["content-length"] = str(len(body))
    return response


def deny(request: Request | None = None) -> Response:
    """The one refusal: 404, a constant body, no ``Vary``, ``ETag`` or cookie of ours."""
    body = constants.PRIVATE_FEED_ERROR_BODY
    head = request is not None and request.method == "HEAD"
    response = Response(
        b"" if head else body,
        status_code=404,
        media_type=constants.JSON_MEDIA_TYPE,
        headers=_headers(),
    )
    if head:
        response.headers["content-length"] = str(len(body))
    return response


def _throttled(request: Request, retry_after: float) -> Response:
    return _answer(
        request,
        constants.PRIVATE_FEED_THROTTLED_BODY,
        429,
        constants.JSON_MEDIA_TYPE,
        _headers(**{"Retry-After": str(int(retry_after))}),
    )


def _unavailable(request: Request) -> Response:
    body = b'{"detail":"Service unavailable","code":"service_unavailable"}'
    return _answer(request, body, 503, constants.JSON_MEDIA_TYPE, _headers())


async def _padded(response: Response, started: float) -> Response:
    """``response``, no sooner than the floor after ``started``."""
    remaining = constants.FEED_DENY_FLOOR_SECONDS - (time.perf_counter() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)
    return response


def _item_urls(request: Request, access: FeedAccess, items: list) -> list:
    """A public calendar's events link to their public page, any other's to the console (the
    absolute editor address, which only a signed-in member can open)."""
    if access.calendar.visibility == "public":
        return items
    return [
        dataclasses.replace(
            item,
            url=_urls.absolute(request, f"{constants.EDITOR_URL}/{item.event.id}"),
        )
        for item in items
    ]


async def _viewer(request: Request, access: FeedAccess, db) -> SourceViewer | None:
    """The link's owner as a plugin source sees them, or ``None`` (then no plugin source is
    called and the feed is served as before): a failing directory is no reason to refuse a
    link that already passed every check."""
    try:
        return await feed_viewer(
            request.app,
            db,
            user_id=access.row.user_id,
            tenant_id=access.row.tenant_id,
            request=request,
        )
    except Exception as exc:
        _log.error("events: a private feed's viewer could not be built (%s)", type(exc).__name__)
        return None


async def _body(request: Request, access: FeedAccess, db) -> tuple[bytes, bool]:
    now = _clock.now()
    read = await feed_events(
        db,
        calendar_id=access.row.calendar_id,
        locale=access.row.locale,
        default_locale=locales.default(),
        now=now,
        url_for=lambda slug, loc: _urls.absolute(request, _urls.event_path(slug, loc)),
        events=access.events(),
    )
    plug = await plugin_events(
        db,
        request,
        read,
        who=access.who,
        viewer=await _viewer(request, access, db),
        calendar_id=access.row.calendar_id,
        now=now,
        locale=access.row.locale,
    )
    body = ics_file(
        _item_urls(request, access, read.items),
        name=access.calendar.name,
        timezone=timezones.effective(access.calendar.default_timezone),
        now=now,
        extra=plug.events,
    )
    return body, read.truncated or plug.truncated


async def _serve(request: Request, token: str) -> tuple[Response, TokenRow] | None:
    """The feed and the link it came from, or ``None`` for every refusal. Raises only for an
    internal failure."""
    if not well_formed(token):
        return None  # nothing it could name: no database read at all
    app = request.app
    factory = app.state.sm.db.session_factory
    with no_tenant():  # a visitor's session or header tenant is left; only the row's counts
        async with factory() as db:
            row = await lookup(db, token)
        if row is None or not valid_tenant(row.tenant_id):
            return None
        with tenant_scope(row.tenant_id):
            async with factory() as db:
                try:
                    access = await resolve(app, db, request, row, host_tenant=host_tenant(request))
                except Exception as exc:
                    # The directory, the membership store or a grant source failing for a link
                    # that exists must not look different from one that does not: it is the
                    # refusal, and the class is logged (never the message).
                    _log.error("events: a private feed check failed (%s)", type(exc).__name__)
                    return None
                if access is None:
                    return None
                body, truncated = await _body(request, access, db)
        # Only a link that is *served* earns the pool junk cannot flood: a refused one (revoked,
        # lost access, ...) keeps its window with the invented tokens', so no sequence of requests
        # tells "a row exists but is refused" from "no such token".
        THROTTLE.promote(token)
    extra = {TRUNCATED_HEADER: "1"} if truncated else {}
    headers = _headers(constants.PRIVATE_FEED_CACHE_CONTROL, **extra)
    return _answer(request, body, 200, constants.ICS_MEDIA_TYPE, headers), row


@router.api_route(
    f"/{constants.FEED_PATH_SEGMENT}/{{token}}.ics", methods=_METHODS, response_model=None
)
async def private_feed(request: Request, token: str) -> Response:
    started = time.perf_counter()
    if (retry_after := THROTTLE.hit(token)) is not None:
        return _throttled(request, retry_after)
    try:
        served = await _serve(request, token)
    except Exception as exc:  # the class only: its message can carry the address
        _log.error("events: a private feed failed (%s)", type(exc).__name__)
        return _unavailable(request)
    if served is None:
        return await _padded(deny(request), started)
    response, row = served
    with no_tenant():
        await touch_last_used(request.app.state.sm.db.session_factory, row, now=_clock.now())
    return response
