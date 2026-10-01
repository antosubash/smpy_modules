"""Slug derivation for categories and tags.

:func:`suffixed` is the one piece articles share — see
:func:`news.content._slugs.free_slug` for why the loop around it is not
shared too.

Kept in this module rather than pulled from a dependency: the rule has to stay
stable forever, because a slug that shifts under an existing category silently
breaks every ``/news?category=…`` link already in the wild.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

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


_TAG_SEPARATORS = re.compile(r"[\W_]+")


def tag_slug(value: str, *, max_length: int = 60) -> str:
    """Unicode-safe slug for tags: ``"中文"`` stays ``"中文"``.

    NFKC-normalised and lowercased, runs of anything that is not a letter or
    number collapse to one dash. Returns ``""`` when nothing alphanumeric is
    left (``"???"``, emoji-only) — callers must reject that rather than invent
    a stand-in slug, or two unrelated tags collapse onto one row.
    """
    folded = unicodedata.normalize("NFKC", value).lower()
    slug = _TRIM.sub("", _TAG_SEPARATORS.sub("-", folded))[:max_length]
    slug = _TRIM.sub("", slug)
    return slug if any(ch.isalnum() for ch in slug) else ""


def suffixed(base: str, *, max_length: int, limit: int) -> Iterator[str]:
    """``base-2``, ``base-3`` … ``base-{limit}``, each fitting ``max_length``.

    The suffix is appended *inside* ``max_length`` rather than past it, so a
    long name cannot produce a slug the column will reject.

    Shared with :func:`news.content._slugs.free_slug` because this truncation
    rule is load-bearing over there: it prefilters the taken set by a stem, and
    that is only sound while every candidate still starts with the same cut of
    ``base``. Two copies of the rule could stop agreeing about that silently,
    and the symptom would be handing an author a slug already in use.
    """
    for n in range(2, limit + 1):
        suffix = f"-{n}"
        yield f"{base[: max_length - len(suffix)]}{suffix}"


def unique_slug(value: str, taken: set[str], *, max_length: int = 80) -> str:
    """``slugify`` plus a numeric suffix until the result is unused.

    Tries far more candidates than the article equivalent
    (:func:`news.content._slugs.free_slug`) and raises rather than returning a
    sentinel, and both differences are deliberate. A category or tag slug is
    derived from a name and only has to be *some* free one, so giving up early
    would block a rename for no reader-visible gain; running out is a genuine
    impossibility rather than a case to report. An article slug is a URL a
    person will keep, so news stops at ``MAX_SLUG_ATTEMPTS`` and asks the author
    to choose instead of minting ``my-headline-731``.

    Only the candidate *shape* is shared, via :func:`suffixed`. That is the part
    that must never drift; the cap and the failure mode are each caller's own.
    """
    base = slugify(value, max_length=max_length)
    if base not in taken:
        return base
    for candidate in suffixed(base, max_length=max_length, limit=999):
        if candidate not in taken:
            return candidate
    raise ValueError(f"Could not derive a unique slug from {value!r}.")
