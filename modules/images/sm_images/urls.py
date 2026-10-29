"""Where an image's bytes are fetched from.

Every URL carries ``?v=`` naming the exact bytes - :func:`sm_images.cache.version`,
the generation plus a digest of the object key. A regenerated rendition or a
new display copy lives under a new key, so it gets a new URL, and an old URL
may stay cached forever (``cache.SHARED`` is ``immutable``) because the route
refuses to call a request "current" unless its ``v`` matches.

``public_asset_base_url`` (a boot-time setting, read in ``on_startup`` through
:func:`configure`) puts a CDN in front of the **public twin** for public
collections only. A private or internal collection's URL is always this app's
access-checked admin route: a CDN must never hold what the policy guards.
It is single-tenant only: on a multi-tenant host the anonymous twin learns its
tenant from the request (the organisation's subdomain), which one CDN origin
does not carry, so every URL behind it would 404. There the base is ignored,
with one warning at boot.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from sm_images import cache, constants
from sm_images._tenancy_mode import TenancyMode
from sm_images.models import Visibility

__all__ = [
    "configure",
    "display_url",
    "image_path",
    "public_display_url",
    "public_image_path",
    "public_rendition_url",
    "rendition_url",
]

logger = logging.getLogger("sm_images.urls")

_public_base = ""


def configure(public_asset_base_url: str, mode: TenancyMode | None = None) -> None:
    """Remember the CDN base (``""`` for none). Called from ``on_startup`` with
    the host's tenancy *mode*; on a multi-tenant host the base is ignored."""
    global _public_base
    base = (public_asset_base_url or "").strip().rstrip("/")
    if base and mode is TenancyMode.MULTI:
        logger.warning(
            "images: public_asset_base_url (%s) is ignored on a multi-tenant host: "
            "a CDN origin carries no tenant, so the public routes behind it would 404",
            base,
        )
        base = ""
    _public_base = base


def image_path(image_id: Any, tail: str) -> str:
    """``/api/images/images/{id}/{tail}`` - the access-checked admin route."""
    return f"{constants.ROUTE_PREFIX_API}/images/{image_id}/{tail}"


def public_image_path(slug: str, image_id: Any, tail: str) -> str:
    """``/api/images/public/c/{slug}/images/{id}/{tail}`` - the anonymous twin."""
    return f"{constants.PUBLIC_API_PREFIX}c/{quote(slug, safe='')}/images/{image_id}/{tail}"


def _rendition_tail(image: Any, rendition: Any) -> str:
    if rendition.image_id != image.id:
        raise ValueError("the rendition is not this image's")
    v = cache.version(rendition.source_generation, rendition.storage_key)
    return f"r/{quote(rendition.size, safe='')}?v={v}"


def _display_tail(image: Any) -> str:
    key = image.display_key or image.storage_key
    return f"display?v={cache.version(image.display_generation or 0, key)}"


def _check(collection: Any, image: Any) -> None:
    if collection.id != image.collection_id:
        raise ValueError("the collection does not hold this image")


def _url(image: Any, tail: str, collection: Any) -> str:
    if collection is not None:
        _check(collection, image)
        if _public_base and collection.visibility == Visibility.PUBLIC:
            return _public_base + public_image_path(collection.slug, image.id, tail)
    return image_path(image.id, tail)


def rendition_url(image: Any, rendition: Any, *, collection: Any = None) -> str:
    """The URL of *rendition* (a ``Rendition`` row of *image*).

    Access is checked by the route, not here: followed by someone who may not
    open the image it is a 404. Behind ``public_asset_base_url`` only when
    *collection* (the image's own) is public and a base is configured.
    """
    return _url(image, _rendition_tail(image, rendition), collection)


def display_url(image: Any, *, collection: Any = None) -> str:
    """The URL of *image*'s display copy (the original when it has none)."""
    return _url(image, _display_tail(image), collection)


def public_rendition_url(collection: Any, image: Any, rendition: Any) -> str:
    """The anonymous twin's URL, for a public page. Behind the CDN when set."""
    _check(collection, image)
    if collection.visibility != Visibility.PUBLIC:
        raise ValueError("only a public collection is served anonymously")
    tail = _rendition_tail(image, rendition)
    return _public_base + public_image_path(collection.slug, image.id, tail)


def public_display_url(collection: Any, image: Any) -> str:
    """The anonymous twin's URL of *image*'s display copy, for a public page."""
    _check(collection, image)
    if collection.visibility != Visibility.PUBLIC:
        raise ValueError("only a public collection is served anonymously")
    return _public_base + public_image_path(collection.slug, image.id, _display_tail(image))
