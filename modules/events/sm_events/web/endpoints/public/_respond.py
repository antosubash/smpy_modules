"""One way for the machine-read routes (feeds, API, sitemap) to answer.

``HEAD`` gets the headers of ``GET`` and no body. The weak ``ETag`` is a digest of the body, the
cache policy is :func:`~sm_events.web.endpoints.public._cache.apply`, and a matching
``If-None-Match`` is a 304 carrying ``ETag``, ``Cache-Control`` and ``Vary``. Call it only for a
row that has passed the gate, so a guessed tag on a hidden address was already a 404.
"""

from __future__ import annotations

from fastapi import Request, Response

from sm_events.core.settings import EventsSettings
from sm_events.web.endpoints.public import _cache

__all__ = ["machine_response"]


def machine_response(
    request: Request,
    settings: EventsSettings,
    body: bytes,
    *,
    media_type: str,
    kind: _cache.Kind,
    headers: dict[str, str] | None = None,
) -> Response:
    head = request.method == "HEAD"
    response = Response(b"" if head else body, media_type=media_type, headers=headers)
    if head:
        response.headers["content-length"] = str(len(body))
    _cache.apply(response, request, settings, kind=kind, etag=_cache.body_etag(body))
    return _cache.not_modified(request, response.headers) or response
