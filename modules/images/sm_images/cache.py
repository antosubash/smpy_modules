"""How an image response may be cached, and its validator.

**Shareable** - ``public, max-age=31536000, immutable`` - only when all four hold:

* the collection is ``public``;
* the route is a rendition or the display copy (never an original);
* it is served through the anonymous twin under ``/api/images/public/``, whose
  answer does not depend on who asks;
* no tenant was picked by anything request-specific. This is the rule of
  records #196 and pagebuilder/news #192 (CLAUDE.md): the request must be a
  request-level ``SINGLE`` serving :data:`~sm_images.tenancy.DEFAULT_TENANT`.
  A multi-tenant host, or a ``SINGLE`` detection under a layer that resolved
  another tenant, answers per tenant, and a shared cache keyed by URL would
  hand one tenant's answer to another.

Immutable is safe because the URL carries ``?v=<display_generation>`` and the
bytes behind a key never change: display and rendition keys are generation-
and attempt-specific (``storage_keys``).

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
from sm_images.tenancy import DEFAULT_TENANT, TenancyMode, mode_of, resolve_public

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
]

RENDITION: Final = "rendition"
DISPLAY: Final = "display"
ORIGINAL: Final = "original"

SHARED: Final = "public, max-age=31536000, immutable"
PRIVATE: Final = "private, max-age=3600"
NO_STORE: Final = "private, no-store"

_WEAK: Final = "W/"
_DIGEST_CHARS: Final = 32


def _shared_tenant(request: Any) -> bool:
    """Whether this request's tenant is the one every request of the host gets."""
    single = request_mode(request, mode_of(request.app)) is TenancyMode.SINGLE
    return single and resolve_public(request) == DEFAULT_TENANT


def cache_headers(
    request: Any, collection: Any, route: str, *, twin: bool = False, protected: bool = False
) -> str:
    """The ``Cache-Control`` for serving *route* of an image in *collection*.

    Decided before the conditional-request check, so a 304 carries it too.
    """
    if route == ORIGINAL and protected:
        return NO_STORE
    if (
        twin
        and route in (RENDITION, DISPLAY)
        and collection.visibility == Visibility.PUBLIC
        and _shared_tenant(request)
    ):
        return SHARED
    return PRIVATE


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
