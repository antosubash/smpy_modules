"""How an image response may be cached, and its validator.

**Shareable** - ``public, max-age=31536000, immutable`` - only when all four hold:

* the collection is ``public``;
* the route is a rendition or the display copy (never an original);
* it is served through the anonymous twin under ``/api/images/public/``, whose
  answer does not depend on who asks;
* no tenant was picked by anything request-specific. This is the rule of
  records #196 and pagebuilder/news #192 (CLAUDE.md): the request must be a
  request-level ``SINGLE`` that fell back to
  :data:`~sm_images.tenancy.DEFAULT_TENANT` itself. ``bind_public`` records,
  before that fallback, whether ``request.state.tenant_id`` was already set
  (:func:`~sm_images.tenancy.tenant_from_request`); set upstream, the tenant
  is request-specific even when it is ``default``. A multi-tenant host answers
  per tenant, and a shared cache keyed by URL would hand one tenant's answer
  to another.

**And the URL names the bytes.** ``?v=`` is :func:`version` - the generation
plus a digest of the object key - and the bytes behind a key never change
(keys are generation- and attempt-specific, ``storage_keys``). A request whose
``v`` is missing or is not the current representation's gets the current
bytes with ``no-cache`` (``public`` or ``private`` as above): a stale URL is
never stored ``immutable`` for bytes it does not name, and an unversioned one
always revalidates.

Everything else is ``private, max-age=3600``, except a **protected original**
(the image has a display copy, or a display mutator has not settled), which is
``private, no-store`` for everyone, the owner included: the browser of someone
allowed to see it once must not keep the unredacted picture.

The **ETag** is strong: a digest of the object key and its size. The key is
generation- and attempt-specific, so a regenerated object always gets a new
tag; the digest keeps the key (tenant, collection and image ids) out of the
header.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from sm_images._tenancy_mode import request_mode
from sm_images.models import Visibility
from sm_images.tenancy import (
    DEFAULT_TENANT,
    TenancyMode,
    mode_of,
    resolve_public,
    tenant_from_request,
)

__all__ = [
    "DISPLAY",
    "NO_STORE",
    "ORIGINAL",
    "PRIVATE",
    "RENDITION",
    "SHARED",
    "cache_headers",
    "etag",
    "if_range_ok",
    "not_modified",
    "version",
]

RENDITION: Final = "rendition"
DISPLAY: Final = "display"
ORIGINAL: Final = "original"

SHARED: Final = "public, max-age=31536000, immutable"
PRIVATE: Final = "private, max-age=3600"
NO_STORE: Final = "private, no-store"
PUBLIC_NO_CACHE: Final = "public, no-cache"
PRIVATE_NO_CACHE: Final = "private, no-cache"

_WEAK: Final = "W/"
_DIGEST_CHARS: Final = 32
_VERSION_CHARS: Final = 12


def _shared_tenant(request: Any) -> bool:
    """Whether this request's tenant is the host-wide single-tenant fallback."""
    if tenant_from_request(request):
        return False
    single = request_mode(request, mode_of(request.app)) is TenancyMode.SINGLE
    return single and resolve_public(request) == DEFAULT_TENANT


def cache_headers(
    request: Any,
    collection: Any,
    route: str,
    *,
    twin: bool = False,
    protected: bool = False,
    current: bool = False,
) -> str:
    """The ``Cache-Control`` for serving *route* of an image in *collection*.

    ``current``: the request's ``?v=`` names the representation being served
    (ignored for an original, whose bytes never change). Decided before the
    conditional-request check, so a 304 carries it too.
    """
    if route == ORIGINAL:
        return NO_STORE if protected else PRIVATE
    shared = twin and collection.visibility == Visibility.PUBLIC and _shared_tenant(request)
    if not current:
        return PUBLIC_NO_CACHE if shared else PRIVATE_NO_CACHE
    return SHARED if shared else PRIVATE


def version(generation: int, key: str) -> str:
    """The ``?v=`` of the object at *key*: its generation and a key digest."""
    digest = hashlib.sha256(key.encode()).hexdigest()[:_VERSION_CHARS]
    return f"{int(generation)}.{digest}"


def etag(key: str, size: int) -> str:
    digest = hashlib.sha256(f"{key}\n{size}".encode()).hexdigest()[:_DIGEST_CHARS]
    return f'"{digest}"'


def not_modified(if_none_match: str | None, tag: str) -> bool:
    """RFC 9110 §13.1.2: ``*`` or any listed tag, compared weakly."""
    if not if_none_match:
        return False
    for candidate in if_none_match.split(","):
        value = candidate.strip()
        if value == "*" or value.removeprefix(_WEAK) == tag:
            return True
    return False


def if_range_ok(if_range: str | None, tag: str) -> bool:
    """Whether a ``Range`` may be honoured: no ``If-Range``, or one naming this
    exact entity (strong comparison). A date or a stale tag gets the whole
    object, so a resumed download never splices two versions."""
    return if_range is None or if_range.strip() == tag
