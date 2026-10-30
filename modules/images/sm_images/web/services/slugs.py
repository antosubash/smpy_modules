"""Slugs: ``[a-z0-9-]``, 1-80 characters."""

from __future__ import annotations

import re
import unicodedata

from sm_images.core import constants

__all__ = ["slugify"]

_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """A slug from a display name: accents folded, everything else a hyphen."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    slug = _NOT_SLUG.sub("-", folded).strip("-")[: constants.SLUG_MAX].strip("-")
    return slug or constants.SLUG_FALLBACK
