"""Auth + CSRF dependencies for pagebuilder admin endpoints.

The pagebuilder module historically assumed the host gated ``/pagebuilder/*``
and ``/api/pagebuilder/*`` via session-cookie middleware. A host that
forgets to mount auth — or one that swaps the users module out — would
expose page CRUD + media upload to the public internet. These helpers
move the gate inside the module so it's secure by default.

The dependencies are intentionally lazy: importing ``auth.deps`` at
module top-level would couple the pagebuilder test app to the users
module's database schema, which we don't want in unit tests.
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from inertia import Inertia
from simple_module_hosting.inertia_deps import get_inertia
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_CSRF_SESSION_KEY = "pagebuilder_csrf_token"
_CSRF_HEADER_NAME = "x-csrf-token"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def get_current_user_or_401(request: Request) -> Any:
    """Return the authenticated user or raise 401.

    Reads ``request.state.user`` (set by the host's auth middleware).
    We don't import ``auth.deps.get_current_user`` because it depends on
    the i18n TranslatorDep — the failure mode we care about is "no auth
    middleware mounted at all", which would leave ``request.state.user``
    unset regardless of which dep we use.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _get_or_create_csrf_token(request: Request) -> str | None:
    """Generate (and persist) the per-session CSRF token.

    Returns ``None`` when the request has no session — happens in the
    bare-FastAPI test app that doesn't mount SessionMiddleware. Callers
    can treat ``None`` as "skip CSRF enforcement" since without a session
    we have no anchor to bind the token to anyway.
    """
    session = request.scope.get("session")
    if session is None:
        return None
    token = session.get(_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_CSRF_SESSION_KEY] = token
    return token


def get_csrf_token(request: Request) -> str:
    """Public dep that returns the current CSRF token, generating if needed.

    Returns an empty string when no session is mounted so view code can
    pass it straight to Inertia props without a None-check.
    """
    return _get_or_create_csrf_token(request) or ""


async def verify_csrf(request: Request) -> None:
    """Enforce ``X-CSRF-Token`` header on every mutating admin request.

    Skipped on safe methods (GET / HEAD / OPTIONS) and when no session is
    mounted (test harnesses without SessionMiddleware). The header value
    is compared in constant time against the per-session token.
    """
    if request.method not in _UNSAFE_METHODS:
        return
    session = request.scope.get("session")
    if session is None:
        return
    expected = session.get(_CSRF_SESSION_KEY)
    received = request.headers.get(_CSRF_HEADER_NAME)
    if not expected or not received or not secrets.compare_digest(
        str(expected), str(received)
    ):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")


async def share_csrf_to_inertia(
    request: Request,
    inertia: Annotated[Inertia, Depends(get_inertia)],
) -> None:
    """Surface the CSRF token to the React client via shared Inertia props.

    The companion :class:`CsrfCookieMiddleware` writes the same value to
    a non-``HttpOnly`` cookie so the JS layer can read it back for
    sub-resources that don't go through Inertia page props (notably
    multipart media uploads, which can't easily include the token via
    JSON props).

    We share via Inertia props rather than a route-level
    ``response.set_cookie`` because FastAPI doesn't merge a dependency's
    cookie writes into a ``Response`` returned by the handler — and the
    Inertia view handlers all return ``InertiaResponse`` directly.
    """
    settings = _get_settings(request)
    if not settings.csrf_protect:
        return
    token = _get_or_create_csrf_token(request)
    if token is None:
        return
    inertia.share(csrf={"token": token, "header": "X-CSRF-Token"})


class CsrfCookieMiddleware:
    """Mirror the session's CSRF token to a JS-readable cookie.

    Lives in a middleware (not the share dep) because FastAPI doesn't
    merge a dep's cookie writes into a ``Response`` returned by the
    handler — Inertia views always return one, so the dep route is a
    dead end for cookie setting.

    Two short-circuits keep this off the hot path: requests outside the
    admin prefixes (public viewer, static assets) skip the response
    wrapper entirely, and the wrapper itself emits no ``Set-Cookie`` when
    the request already arrived with a cookie matching the session
    token.
    """

    def __init__(self, app: ASGIApp, admin_prefixes: tuple[str, ...] = ()) -> None:
        self.app = app
        self.admin_prefixes = admin_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if self.admin_prefixes and not any(
            scope["path"].startswith(p) for p in self.admin_prefixes
        ):
            await self.app(scope, receive, send)
            return

        # Both the switch and the cookie's name are read here rather than
        # captured in ``__init__``: middleware is installed while the app is
        # built, which is before the host hydrates settings from the database,
        # so a value captured then would be the pydantic default for the life
        # of the process.
        settings = _settings_from_scope(scope)
        if settings is None or not settings.csrf_protect:
            await self.app(scope, receive, send)
            return
        cookie_name = settings.csrf_cookie_name
        cookie_attr = f"{cookie_name}="

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                session = scope.get("session")
                token = (
                    session.get(_CSRF_SESSION_KEY) if isinstance(session, dict) else None
                )
                if token and _request_cookie_value(scope, cookie_attr) != token:
                    headers = MutableHeaders(scope=message)
                    headers.append(
                        "set-cookie",
                        f"{cookie_name}={token}; Path=/; SameSite=Strict",
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _request_cookie_value(scope: Scope, attr: str) -> str | None:
    """Read the cookie value matching ``attr`` (e.g. ``"pagebuilder_csrf="``).

    Hand-rolled instead of using ``starlette.requests.cookies`` to avoid
    re-parsing the whole Cookie header for one attribute on every admin
    request.
    """
    for name, value in scope.get("headers", ()):
        if name == b"cookie":
            for piece in value.decode("latin-1").split(";"):
                trimmed = piece.lstrip()
                if trimmed.startswith(attr):
                    return trimmed[len(attr):]
    return None


def _settings_from_scope(scope: Scope):
    """The live settings, or ``None`` when the module isn't mounted yet.

    ASGI middleware gets a scope, not a ``Request``; ``scope["app"]`` is the
    same object ``request.app`` would resolve to.
    """
    app = scope.get("app")
    services = getattr(getattr(app, "state", None), "pagebuilder", None)
    return getattr(services, "settings", None)


def _get_settings(request: Request):
    """Resolve the pagebuilder settings from app state.

    Mirrors :func:`pagebuilder.deps.get_settings` but inlined to avoid an
    import cycle: ``deps`` imports from settings, settings is fine, but
    security depending on deps would force security to import the
    MediaService transitively.
    """
    return request.app.state.pagebuilder.settings


async def require_user_if_configured(request: Request) -> Any:
    """Apply :func:`get_current_user_or_401` when ``requires_auth`` is set.

    Always installed, and decides per request. The routers are built before
    the host hydrates settings from the database, so a dependency list
    assembled from the flag at that point would be frozen at the pydantic
    default — leaving the Settings screen showing a switch that changes
    nothing until someone edits an environment that no longer exists.
    """
    if not _get_settings(request).requires_auth:
        return None
    return await get_current_user_or_401(request)


async def verify_csrf_if_configured(request: Request) -> None:
    """Apply :func:`verify_csrf` when ``csrf_protect`` is set."""
    if not _get_settings(request).csrf_protect:
        return
    await verify_csrf(request)


def build_admin_dependencies() -> list[Any]:
    """Mutating-side dependencies applied to the API router.

    Returned items are ``Depends(...)`` wrappers ready to be passed to
    ``APIRouter(dependencies=...)``. The dependency order matters: auth
    runs first so an unauthenticated request gets 401 (the more useful
    error) before CSRF fails it with 403.
    """
    return [Depends(require_user_if_configured), Depends(verify_csrf_if_configured)]


def build_view_dependencies() -> list[Any]:
    """View-side dependencies applied to the Inertia view router.

    Mirrors :func:`build_admin_dependencies` but emits the CSRF token
    via Inertia shared-props + cookie instead of enforcing it (Inertia
    GETs are safe methods, so verification is a no-op anyway).
    ``share_csrf_to_inertia`` already checks the flag itself.
    """
    return [Depends(require_user_if_configured), Depends(share_csrf_to_inertia)]
