"""Where an image's bytes are fetched from.

Every URL is versioned with ``?v=<display_generation>``: a new display copy
means new renditions under new keys, so a new URL, and the old one may stay
cached forever (``cache.SHARED`` is ``immutable``).

``public_asset_base_url`` (a boot-time setting, read in ``on_startup`` through
:func:`configure`) puts a CDN in front of the **public twin** for public
collections only. A private or internal collection's URL is always this app's
access-checked admin route: a CDN must never hold what the policy guards.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from sm_images import constants
from sm_images.models import Visibility

__all__ = [
    "configure",
    "image_path",
    "public_image_path",
    "public_rendition_url",
    "rendition_url",
]

_public_base = ""


def configure(public_asset_base_url: str) -> None:
    """Remember the CDN base (``""`` for none). Called from ``on_startup``."""
    global _public_base
    _public_base = (public_asset_base_url or "").strip().rstrip("/")


def image_path(image_id: Any, tail: str) -> str:
    """``/api/images/images/{id}/{tail}`` - the access-checked admin route."""
    return f"{constants.ROUTE_PREFIX_API}/images/{image_id}/{tail}"


def public_image_path(slug: str, image_id: Any, tail: str) -> str:
    """``/api/images/public/c/{slug}/images/{id}/{tail}`` - the anonymous twin."""
    return f"{constants.PUBLIC_API_PREFIX}c/{quote(slug, safe='')}/images/{image_id}/{tail}"


def _tail(image: Any, size: str) -> str:
    return f"r/{quote(size, safe='')}?v={int(image.display_generation or 0)}"


def _check(collection: Any, image: Any) -> None:
    if collection.id != image.collection_id:
        raise ValueError("the collection does not hold this image")


def rendition_url(image: Any, size: str, *, collection: Any = None) -> str:
    """The URL of *image*'s rendition *size*.

    Access is checked by the route, not here: followed by someone who may not
    open the image it is a 404. Behind ``public_asset_base_url`` only when
    *collection* (the image's own) is public and a base is configured.
    """
    if collection is not None:
        _check(collection, image)
        if _public_base and collection.visibility == Visibility.PUBLIC:
            return _public_base + public_image_path(collection.slug, image.id, _tail(image, size))
    return image_path(image.id, _tail(image, size))


def public_rendition_url(collection: Any, image: Any, size: str) -> str:
    """The anonymous twin's URL, for a public page. Behind the CDN when set."""
    _check(collection, image)
    if collection.visibility != Visibility.PUBLIC:
        raise ValueError("only a public collection is served anonymously")
    return _public_base + public_image_path(collection.slug, image.id, _tail(image, size))
