"""Slug derivation for categories and tags.

Kept in this module rather than pulled from a dependency: the rule has to stay
stable forever, because a slug that shifts under an existing category silently
breaks every ``/news?category=…`` link already in the wild.
"""

from __future__ import annotations

import re
import unicodedata

_SEPARATORS = re.compile(r"[^a-z0-9]+")
_TRIM = re.compile(r"^-+|-+$")


def slugify(value: str, *, fallback: str = "item", max_length: int = 80) -> str:
    """Lowercase ASCII slug: ``"Field notes"`` → ``"field-notes"``.

    Accents fold to their base letter (``"Étude"`` → ``"etude"``) rather than
    being dropped, so two visually distinct categories do not collapse onto the
    same slug. A value with no usable characters at all — punctuation, or a
    script that does not transliterate — yields ``fallback`` instead of an
    empty string, which would violate the column's uniqueness on the second
    such category.
    """
    folded = unicodedata.normalize("NFKD", value)
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    slug = _SEPARATORS.sub("-", ascii_only.lower())
    slug = _TRIM.sub("", slug)[:max_length]
    # The truncation above can leave a trailing separator; trim again so the
    # slug never ends in a dash.
    slug = _TRIM.sub("", slug)
    return slug or fallback


def unique_slug(value: str, taken: set[str], *, max_length: int = 80) -> str:
    """``slugify`` plus a numeric suffix until the result is unused.

    The suffix is appended inside ``max_length`` rather than past it, so a
    long name cannot produce a slug the column will reject.
    """
    base = slugify(value, max_length=max_length)
    if base not in taken:
        return base
    for n in range(2, 1000):
        suffix = f"-{n}"
        candidate = f"{base[: max_length - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
    raise ValueError(f"Could not derive a unique slug from {value!r}.")
