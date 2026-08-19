"""CSRF protection for the AI settings endpoints.

This module stores provider API keys, and its write surface can redirect
``chat_base_url`` — a forged cross-site PUT could point the stored key at an
attacker's server. The admin API therefore enforces ``X-CSRF-Token`` the same
way pagebuilder's does: a per-session token minted on the admin view, mirrored
to a JS-readable cookie for the fetch client, and verified in constant time on
every unsafe method.

Adapted from ``pagebuilder.security`` rather than imported — a base module
must not depend on a sibling optional module at runtime. Kept always-on and
without the Inertia shared-prop channel: the settings page talks to the API
via fetch, so the cookie is the only client channel it needs. Enforcement is
skipped when no session is mounted (bare-FastAPI test harnesses) because
without a session there is nothing to bind the token to.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import HTTPException, Request
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sm_ai import constants

logger = logging.getLogger(__name__)

_CSRF_SESSION_KEY = "sm_ai_csrf_token"
_warned_no_session = False
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def mint_csrf_token(request: Request) -> None:
    """View-router dependency: ensure the session carries a CSRF token.

    ``CsrfCookieMiddleware`` mirrors it to the JS-readable cookie on the
    response. No-op without a session — there is no anchor to bind to.
    """
    session = request.scope.get("session")
    if session is None:
        return
    if not session.get(_CSRF_SESSION_KEY):
        session[_CSRF_SESSION_KEY] = secrets.token_urlsafe(32)


async def verify_csrf(request: Request) -> None:
    """API-router dependency: enforce ``X-CSRF-Token`` on unsafe methods."""
    if request.method not in _UNSAFE_METHODS:
        return
    session = request.scope.get("session")
    if session is None:
        # Fail-open by design (no session, nothing to bind a token to — see
        # module docstring), but never silently: a host that mounts these
        # routers without SessionMiddleware should know writes are unguarded.
        global _warned_no_session
        if not _warned_no_session:
            _warned_no_session = True
            logger.warning(
                "CSRF enforcement skipped: no session middleware is mounted, "
                "so the AI settings write API is unprotected against "
                "cross-site requests."
            )
        return
    expected = session.get(_CSRF_SESSION_KEY)
    received = request.headers.get(constants.CSRF_HEADER)
    if (
        not expected
        or not received
        # Bytes, not str: compare_digest raises TypeError on non-ASCII str
        # (headers decode as latin-1), which would turn a bad token into a
        # 500 instead of this 403.
        or not secrets.compare_digest(
            str(expected).encode(), received.encode("latin-1")
        )
    ):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")


class CsrfCookieMiddleware:
    """Mirror the session's CSRF token to a JS-readable cookie.

    A middleware (not the mint dep) because FastAPI doesn't merge a
    dependency's cookie writes into a ``Response`` returned by the handler.
    Requests outside the module's prefixes skip the wrapper, and no
    ``Set-Cookie`` is emitted when the request already carried the current
    token.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._prefixes = (constants.ROUTE_PREFIX_API, constants.VIEW_PREFIX)
        self._cookie_attr = f"{constants.CSRF_COOKIE}="

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        # Segment boundary, not bare startswith - "/ai" must not claim a
        # future "/ai-other" route's responses.
        if scope["type"] != "http" or not any(
            path == p or path.startswith(p + "/") for p in self._prefixes
        ):
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                session = scope.get("session")
                token = (
                    session.get(_CSRF_SESSION_KEY) if isinstance(session, dict) else None
                )
                if token and _request_cookie_value(scope, self._cookie_attr) != token:
                    headers = MutableHeaders(scope=message)
                    cookie = f"{constants.CSRF_COOKIE}={token}; Path=/; SameSite=Strict"
                    if scope.get("scheme") == "https":
                        # Not unconditional: dev runs plain HTTP on loopback.
                        cookie += "; Secure"
                    headers.append("set-cookie", cookie)
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _request_cookie_value(scope: Scope, attr: str) -> str | None:
    """Read one cookie value without re-parsing the whole header per request."""
    for name, value in scope.get("headers", ()):
        if name == b"cookie":
            for piece in value.decode("latin-1").split(";"):
                trimmed = piece.lstrip()
                if trimmed.startswith(attr):
                    return trimmed[len(attr) :]
    return None
