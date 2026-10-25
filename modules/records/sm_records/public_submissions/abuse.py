"""The cheap checks a website submission meets before anything is read (#101).

In the order they run, each failing closed: the master switch (the shared
404), then for a ``POST`` the content type (``415``) and the origin (``403``)
— together the CSRF defence of an anonymous write, since there is no session
token to check: ``application/json`` forces a CORS preflight that no policy
here admits, and the ``Origin`` (else ``Referer``) must be this host, the
host's ``public_base_url`` or one the operator listed. The body cap is
:mod:`sm_records._body_limit`, which runs before any of this.

Then, from the submit pipeline, the two rate limits: per IP across every type,
and per type across every IP (a flood from rotating addresses). Both count in
the host's shared ``rate_limit_store`` — Redis when the host has it — under
keys namespaced by tenant, and answer ``429`` with ``Retry-After``.
"""

from __future__ import annotations

import re
from typing import Any, Final
from urllib.parse import urlsplit

from fastapi import Request
from simple_module_core.rate_limit import InProcessWindowStore, WindowStore, parse_rate

from sm_records.deps import get_settings
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.public_submissions.tokens import public_base_url
from sm_records.services.errors import NotFound
from sm_records.services.public import NOT_FOUND

__all__ = [
    "allow",
    "client_ip",
    "count_links",
    "guard",
    "hit",
    "rate_key",
    "rate_store",
    "source_page",
    "switch",
]

_JSON: Final = "application/json"
_LINK_RE: Final = re.compile(r"(?i)\b(?:https?://|www\.)")
_STORE_ATTR: Final = "sm_records_rate_store"


MAX_SOURCE_PAGE: Final = 300


def source_page(request: Request) -> str | None:
    """The path of the page that sent the submission, from the ``Referer``."""
    path = urlsplit(request.headers.get("referer") or "").path
    return path[:MAX_SOURCE_PAGE] or None


def client_ip(request: Request) -> str:
    """The sender's address as the host resolved it — ``ProxyHeaders`` has
    rewritten it by now when ``SM_TRUSTED_PROXY`` is set."""
    return request.client.host if request.client else "unknown"


def _sent_origin(request: Request) -> str | None:
    """The ``Origin`` header, else the ``Referer``'s origin, else ``None``.

    The literal ``null`` is an opaque origin (a sandboxed frame, a redirect
    across sites, a ``file:`` page): it is refused outright rather than
    falling back to a ``Referer`` the same request may also carry."""
    origin = request.headers.get("origin")
    if origin is not None:
        return None if origin.strip().lower() == "null" else origin
    parts = urlsplit(request.headers.get("referer") or "")
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return None


_DEFAULT_PORTS: Final = {"http": 80, "https": 443}

Origin = tuple[str, str, int]


def origin_of(url: str) -> Origin | None:
    """``(scheme, host, port)``: lowercased, a trailing dot dropped from the
    host, the default port filled in, any path ignored. Compared as a tuple,
    never as a string: an IPv6 literal written without its brackets would
    make ``[2001:db8::1]:8443`` and ``[2001:db8::1:8443]`` the same text."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").rstrip(".").lower()
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    return scheme, host, _DEFAULT_PORTS[scheme] if port is None else port


def _same_host(request: Request, sent: Origin) -> bool:
    """The request's own host, by authority only: behind a TLS-terminating
    proxy the scheme this process sees is not the one the browser used, so a
    ``Host`` without a port matches the sent scheme's default port."""
    try:
        parts = urlsplit("//" + (request.headers.get("host") or ""))
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        return False
    return host == sent[1] and (
        port == sent[2] or (port is None and sent[2] == _DEFAULT_PORTS[sent[0]])
    )


def _origin_allowed(request: Request, origin: str) -> bool:
    sent = origin_of(origin)
    if sent is None:
        return False
    if _same_host(request, sent):
        return True
    configured = [*get_settings(request).public_submissions_allowed_origins]
    configured.append(public_base_url(request.app))
    return sent in {origin_of(item) for item in configured if item}


async def switch(request: Request) -> None:
    """The master switch alone: off, every submission route is the 404."""
    if not get_settings(request).public_submissions_enabled:
        raise NotFound(NOT_FOUND)


async def guard(request: Request) -> None:
    """Router dependency, after the tenant binding: the switch, then for a
    write the content type and the origin."""
    await switch(request)
    if request.method != "POST":
        return
    media = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if media != _JSON:
        raise SubmissionRefused("unsupported_media_type", "submissions must be sent as JSON")
    origin = _sent_origin(request)
    if origin is None or not _origin_allowed(request, origin):
        raise SubmissionRefused("bad_origin", "submissions are accepted from this site only")


def rate_store(app: Any) -> WindowStore:
    """The host's shared counter store, else one per app (a bare harness)."""
    store = getattr(getattr(app.state, "sm", None), "rate_limit_store", None)
    if store is not None:
        return store
    store = getattr(app.state, _STORE_ATTR, None)
    if store is None:
        store = InProcessWindowStore()
        setattr(app.state, _STORE_ATTR, store)
    return store


def rate_key(tenant: str, what: str) -> str:
    return f"records:submissions:{tenant}:{what}"


async def allow(request: Request, key: str, rate: str) -> bool:
    """Count one against ``key`` at ``rate``; whether it was still within it.
    For a limit the caller answers silently (the newsletter's per-address
    confirmation budget), where :func:`hit` answers ``429``."""
    spec = parse_rate(rate)
    if spec is None:
        return True
    return bool((await rate_store(request.app).hit(key, spec)).allowed)


async def hit(request: Request, key: str, rate: str) -> None:
    """Count one against ``key`` at ``rate``; ``429`` once it is over."""
    spec = parse_rate(rate)
    if spec is None:
        return
    result = await rate_store(request.app).hit(key, spec)
    if not result.allowed:
        raise SubmissionRefused(
            "rate_limited",
            "too many submissions; try again later",
            headers={"Retry-After": str(result.retry_after)},
        )


def count_links(values: Any) -> int:
    """How many links the visitor's text holds, across every value.

    Iterative: the body is attacker-shaped JSON, and a value nested a few
    hundred levels deep would exhaust the recursion limit (a 500) here."""
    total, stack = 0, [values]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            total += len(_LINK_RE.findall(item))
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
    return total
