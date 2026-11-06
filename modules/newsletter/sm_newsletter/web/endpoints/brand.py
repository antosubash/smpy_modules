"""``GET /newsletter/brand/logo``: the SYSTEM branding logo, for emails (ruling C8).

Branding's own ``/api/branding/logo`` answers with the *requesting* tenant's
override (its subdomain, or a member's active organisation). An email is
opened anywhere, so its logo must not depend on who loads it, and the sender
identity is SYSTEM scope (R7). This route reads ``logo_file_id`` from the
system theme (``app.state.branding.settings``) and fetches it as a *platform*
file, never through a tenant: a tenant's file id pasted into the system setting
misses like an unknown one. Anonymous, ``GET`` only, no tenant binding; 404
when branding is absent or has no logo. The URL alone determines the bytes, so
a request whose ``?v=`` names the served file is ``public`` and immutable.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from sm_newsletter.core import constants
from sm_newsletter.core.errors import NotFound

logger = logging.getLogger(__name__)

try:  # file_storage comes with branding; without either there is no logo to serve
    from file_storage.deps import get_file_storage_service as _storage
except ImportError:  # pragma: no cover - exercised only on a host without file_storage

    async def _storage() -> None:
        return None


router = APIRouter(tags=["newsletter-public"])

_YEAR = 365 * 24 * 60 * 60
_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})


def _system_logo_id(request: Request) -> uuid.UUID:
    theme = getattr(getattr(request.app.state, "branding", None), "settings", None)
    raw = getattr(theme, "logo_file_id", "") or ""
    if not raw:
        raise NotFound()
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise NotFound() from None


def _image_types() -> frozenset[str]:
    try:
        from branding.images import ALLOWED_IMAGE_TYPES
    except ImportError:  # pragma: no cover
        return _IMAGE_TYPES
    return frozenset(ALLOWED_IMAGE_TYPES)


@router.get(constants.BRAND_LOGO_PATH, response_model=None)
async def brand_logo(request: Request, storage: Any = Depends(_storage)) -> Response:
    file_id = _system_logo_id(request)
    if storage is None:
        raise NotFound()
    from file_storage.downloads import RedirectDownload
    from file_storage.service import StoredFileNotFoundError

    try:
        download = await storage.download(file_id, platform=True)
    except StoredFileNotFoundError:
        logger.warning("newsletter: the system logo %s is not a platform file", file_id)
        raise NotFound() from None
    content_type = (download.file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in _image_types():
        raise NotFound()
    if isinstance(download, RedirectDownload):
        return RedirectResponse(url=download.url, status_code=302)  # presigned: never cached
    versioned = request.query_params.get("v") == str(file_id)
    cache = f"public, max-age={_YEAR}, immutable" if versioned else "no-cache"
    return StreamingResponse(
        download.body,
        media_type=content_type,
        headers={
            "Cache-Control": cache,
            "Content-Length": str(download.file.size_bytes),
            "X-Content-Type-Options": "nosniff",
        },
    )
