"""Exception mapping shared by every Records API (and view) route.

FastAPI's ``exception_handler`` lives on the app, and this module owns only
``endpoints/**`` — not ``module.py``, so there is no hook here to register one
against. A custom :class:`~fastapi.routing.APIRoute` gets the same effect
scoped to exactly the routers built in this package: every
:class:`~sm_records.services.errors.RecordsError` (and the query grammar's
:class:`~sm_records.index.query.QueryError`) raised inside a handler becomes
the JSON shape the API contract promises, with no per-endpoint try/except to
keep in sync across a dozen routes.

**A caught exception is one the session never hears about, so the rollback is
ours to do.** Catching here means the handler returns a response rather than
raising, ``get_db`` resumes normally, finds the has-writes flag its
``after_flush`` listener set, and commits — so a refused delete that had
already nulled one referrer before meeting a ``restrict`` deeper down
committed that rewrite under a 409. Every error path below therefore rolls the
request's session back explicitly, and clears the flag so ``get_db``'s own
exit takes the read-only branch. The session is the one
:func:`sm_records.deps.request_db` parked on ``request.scope``.

**Two route classes, because two routers owe their callers two different
answers.** :class:`RecordsErrorRoute` serves ``/api/records/*`` and answers
JSON, always — including for the exceptions nobody anticipated, which used to
fall through to the host's handler and come back as a 42 KB Inertia HTML
document to a client that had sent ``Accept: application/json``, with the
request's session never rolled back. :class:`RecordsViewErrorRoute` serves the
Inertia screens under ``/admin/records/*``, where the same ``NotFound`` has to
be the host's error *page*: a stale bookmark, a renamed type or a record
purged in another tab dumped a JSON blob into the browser window, while a
FastAPI validation error on the very same screen rendered HTML.

What each mapped exception's body looks like lives next door in
:mod:`sm_records.endpoints.api._error_bodies`, split off for the file cap.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from sm_records.deps import request_session
from sm_records.endpoints.api._error_bodies import response_for
from sm_records.index.query import QueryError
from sm_records.services._common import SESSION_HAS_WRITES_KEY
from sm_records.services.errors import RecordsError

__all__ = ["RecordsErrorRoute", "RecordsViewErrorRoute"]

logger = logging.getLogger(__name__)

INTERNAL_ERROR = "internal error"
"""What an unanticipated failure says on the JSON API. Deliberately opaque:
the detail goes to the log under the correlation id the response already
carries as ``x-correlation-id``, and a stack-derived message on an API is an
information leak with no caller who can act on it."""


_RERAISE = (StarletteHTTPException, RequestValidationError)
"""Always somebody else's: FastAPI raises both from inside the route handler,
and the host's handlers for them already content-negotiate."""


def _host_handles(request: Request, exc: Exception) -> bool:
    """Has the app registered a handler for *this* exception class?

    The rule the catch-all needs, stated once: an exception somebody answers
    deliberately is not an unhandled one, whatever this module has heard of.
    Read off ``app.exception_handlers`` rather than hard-coded, so a host that
    registers its own domain exception keeps getting its own status — the
    framework registers ``NotFoundError`` exactly that way.

    ``Exception`` itself is excluded on purpose: the host registers a
    last-resort handler under that key (``_error_handlers`` renders the SPA
    error document from it), and honouring it would re-raise everything and
    leave the JSON API answering HTML — which is the whole defect.
    """
    if isinstance(exc, _RERAISE):
        return True
    handlers = getattr(request.app, "exception_handlers", None) or {}
    return any(
        key is not Exception and isinstance(key, type) and isinstance(exc, key) for key in handlers
    )


def _correlation(request: Request) -> str:
    """The request's correlation id, for the log line that names the failure.

    ``request.state`` first (``CorrelationIdMiddleware`` puts it there and
    echoes it as ``x-correlation-id``), the context variable second, and an
    empty string when neither exists — a module that declined to log because
    the host does not run that middleware would be the wrong kind of strict.
    """
    cid = getattr(request.state, "correlation_id", None)
    if cid:
        return str(cid)
    try:
        from simple_module_hosting.logging import correlation_id

        return correlation_id.get("")
    except Exception:  # pragma: no cover - a framework without the context var
        return ""


async def _discard_writes(request: Request) -> None:
    """Undo whatever the refused call wrote before it refused.

    See the module docstring: without this the response says 409 and the
    request still commits.
    """
    session = request_session(request)
    if session is None:  # pragma: no cover - every route here uses ``request_db``
        return
    await session.rollback()
    session.info.pop(SESSION_HAS_WRITES_KEY, None)


async def _error_page(request: Request, exc: Exception) -> Response:
    """The host's Inertia error document for a view route's refusal.

    ``render_error_page`` is imported at call time and behind a guard, because
    it is the host's and this module is published on its own: a harness that
    mounted these routers without ``app.state.sm.inertia_config`` — and an
    older framework that does not export the function — must still get an
    answer rather than an ``AttributeError`` on top of the original refusal.
    The JSON body is that fallback, which is exactly what this route class
    used to send unconditionally.
    """
    config = getattr(getattr(request.app.state, "sm", None), "inertia_config", None)
    if config is None:
        return await response_for(request, exc)
    try:
        from simple_module_hosting._error_handlers import render_error_page

        status = getattr(exc, "status_code", 400)
        detail = getattr(exc, "detail", None) or str(exc)
        return await render_error_page(request, status, detail)
    except Exception:  # pragma: no cover - a host whose error page is itself broken
        logger.exception("records: rendering the error page failed; answering JSON")
        return await response_for(request, exc)


class RecordsErrorRoute(APIRoute):
    """The JSON API's route class: every failure leaves as JSON."""

    views = False

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            try:
                return await handler(request)
            except (RecordsError, QueryError) as exc:
                response = (
                    await _error_page(request, exc)
                    if self.views
                    else await response_for(request, exc)
                )
                await _discard_writes(request)
                return response
            except Exception as exc:
                if _host_handles(request, exc):
                    # Not unanticipated: somebody upstream registered a handler
                    # for this exact class and it produces a status of its own.
                    # Without this branch the catch-all turned every 400 the
                    # grammar raises and every 422 FastAPI raises for a bad
                    # query parameter into a 500.
                    raise
                # The rollback is ours either way — see the module docstring:
                # a caught exception is one the session never hears about, and
                # ``get_db`` would otherwise find the has-writes flag and
                # commit whatever the failed handler had already written.
                await _discard_writes(request)
                if self.views:
                    # A view's unanticipated failure belongs to the host's own
                    # handler, which renders the 500 page every other screen in
                    # the app already shows.
                    raise
                logger.exception(
                    "records: unhandled %s on %s [%s]",
                    type(exc).__name__,
                    request.url.path,
                    _correlation(request),
                )
                return JSONResponse({"detail": INTERNAL_ERROR}, status_code=500)

        return wrapped


class RecordsViewErrorRoute(RecordsErrorRoute):
    """The Inertia screens' route class: a refusal is a rendered error page.

    Only the *mapped* errors change hands — a ``NotFound`` for a type key that
    no longer exists, a ``Forbidden`` from ``allowed_roles``, a ``QueryError``
    from a deep link with a bad ``?sort=``. Everything else is re-raised for
    the host, which already renders an error page for it; this class exists
    because a ``RecordsError`` never reached that handler at all, and answered
    a browser with a JSON blob in the window.
    """

    views = True
