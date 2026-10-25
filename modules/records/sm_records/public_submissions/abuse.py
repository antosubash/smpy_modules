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
    "client_ip",
    "count_links",
    "guard",
    "hit",
    "rate_key",
    "rate_store",
]

_JSON: Final = "application/json"
_LINK_RE: Final = re.compile(r"(?i)\b(?:https?://|www\.)")
_STORE_ATTR: Final = "sm_records_rate_store"


def client_ip(request: Request) -> str:
    """The sender's address as the host resolved it — ``ProxyHeaders`` has
    rewritten it by now when ``SM_TRUSTED_PROXY`` is set."""
    return request.client.host if request.client else "unknown"


def _sent_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin and origin != "null":
        return origin.rstrip("/").lower()
    parts = urlsplit(request.headers.get("referer") or "")
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}".lower()
    return None


def _origin_allowed(request: Request, origin: str) -> bool:
    parts = urlsplit(origin)
    host = (request.headers.get("host") or "").lower()
    # The request's own host, by authority only: behind a TLS-terminating
    # proxy the scheme this process sees is not the one the browser used.
    if host and parts.netloc == host:
        return True
    allowed = set(get_settings(request).public_submissions_allowed_origins)
    base = public_base_url(request.app).lower()
    if base:
        allowed.add(base)
    return origin in allowed


async def guard(request: Request) -> None:
    """Router dependency, after the tenant binding: the switch, then for a
    write the content type and the origin."""
    if not get_settings(request).public_submissions_enabled:
        raise NotFound(NOT_FOUND)
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
    """How many links the visitor's text holds, across every value."""
    if isinstance(values, str):
        return len(_LINK_RE.findall(values))
    if isinstance(values, dict):
        return sum(count_links(value) for value in values.values())
    if isinstance(values, (list, tuple)):
        return sum(count_links(value) for value in values)
    return 0
