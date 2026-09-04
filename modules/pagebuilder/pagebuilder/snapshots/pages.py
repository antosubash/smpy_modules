"""Turning a ``Page`` row into bundle JSON and back.

Kept apart from capture and apply because ``PAGE_FIELDS`` is the part most
likely to drift as ``Page`` grows a column — a reviewer should be able to see
the whole list at once and notice what is missing from it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pagebuilder import locales
from pagebuilder.models import Page, PageStatus

PageKey = tuple[str, str]
"""``(locale, slug)`` — what identifies a page inside a bundle.

A slug alone stopped being an identity when pages gained a language: an
English and a German page may both be ``about``. Every map the snapshot layer
keys by page is keyed by this, so the two cannot collapse into one.
"""

PAGE_FIELDS: tuple[str, ...] = (
    "title",
    "meta_title",
    "meta_description",
    "og_image",
    "canonical_url",
    "index_in_search",
    "json_ld",
    "show_in_header_nav",
    "show_in_footer",
    "is_template",
    "translation_group",
    "draft_data",
    "published_data",
)
"""Authored columns carried verbatim in a bundle.

``translation_group`` is carried even though it is a generated key, because it
is the only thing tying a page to its counterparts: dropped, a restored site
would hold the same translations as unrelated documents, each alone in its
language with no way to rebuild the link.

Excluded on purpose: ``id`` and ``parent_id`` are host-local (the parent
travels as a slug); ``locale`` because it is identity rather than content and
is written only when a page is created — see :func:`apply_payload`;
``deleted_at`` because trashed pages are never captured; ``rejection_note``
because it is a workflow artefact rather than content; and the ``AuditMixin``
timestamps, which describe this host's history rather than the content's.
"""


MEDIA_FIELDS: tuple[str, ...] = ("og_image", "json_ld")
"""Fields outside the block data that can still hold a media URL.

``og_image`` is routinely set to a media-library URL — the media grid offers
"copy URL" for exactly that — and ``json_ld`` can embed one under ``image``.
Both are host-local UUID filenames, so they need the same sentinel round-trip
the block data gets; carried verbatim they 404 on any other host.
"""

_DATETIME_FIELDS: tuple[str, ...] = ("publish_at", "unpublish_at")
"""Schedules, carried as ISO-8601 strings because JSON has no datetime."""


def normalise_locale(raw: Any) -> str:
    """A bundle's language tag as this host should store it.

    Three cases, in order. A tag this host publishes comes back in the
    *configured* spelling, so ``DE`` and ``de`` cannot become two pages. A
    well-formed tag it does not publish is kept verbatim: those pages are
    inert — nothing routes ``/fr/p/…`` unless ``fr`` is configured — but they
    are still the site's content, and folding them into the default locale
    would make every one of them collide with its English counterpart and
    overwrite it, which is the exact data loss this keying exists to stop.
    Adding ``fr`` later simply lights them up. Anything else, including the
    absent key a version 1 document has, reads as the default locale.
    """
    # Guarded rather than handed straight to `locales.resolve`, which is
    # typed for `str | None`: this value came out of JSON, so it can be any
    # type at all, and widening that function for one untrusted caller would
    # push the problem onto every other one.
    if not isinstance(raw, str):
        return locales.default()
    resolved = locales.resolve(raw)
    if resolved is not None:
        return resolved
    tag = raw.strip().lower()
    if tag and len(tag) <= locales.MAX_LOCALE_LEN and locales.LOCALE_PATTERN.match(tag):
        return tag
    return locales.default()


def payload_locale(payload: dict[str, Any]) -> str:
    """The locale a page document is in, defaulting a v1 bundle's absence.

    Version 1 predates the column, so a document without ``locale`` came from
    a site that had only the default one — that is not a guess, it is what the
    schema guaranteed when the bundle was written.
    """
    return normalise_locale(payload.get("locale"))


def payload_key(payload: dict[str, Any]) -> PageKey:
    """The ``(locale, slug)`` a page document claims."""
    return payload_locale(payload), payload["slug"]


def page_to_payload(page: Page, parent_slug: str | None) -> dict[str, Any]:
    """Serialise *page* for the bundle, with its parent named by slug."""
    payload: dict[str, Any] = {
        "slug": page.slug,
        "locale": page.locale,
        "parent_slug": parent_slug,
        "status": page.status.value,
    }
    for field in PAGE_FIELDS:
        payload[field] = getattr(page, field)
    for field in _DATETIME_FIELDS:
        value: datetime | None = getattr(page, field)
        payload[field] = value.isoformat() if value is not None else None
    return payload


def apply_payload(page: Page, payload: dict[str, Any]) -> None:
    """Write *payload* onto *page*, leaving ``parent_id`` to the second pass.

    ``locale`` is not among the fields written. A page's language is fixed for
    its lifetime — moving one would strand its slug in the old language and
    orphan the redirect pointing at it — so the caller sets it once, when it
    creates the row, and a restore matching an existing page leaves it alone.

    An absent *schedule* is written as ``None`` rather than skipped: restoring
    is not merging, so a schedule the bundle does not carry must be cleared,
    not inherited from whatever was there before.

    Other absent keys are left untouched. ``page_to_payload`` always emits
    every ``PAGE_FIELDS`` key, so a bundle this code wrote never has any — and
    ``plan._fields_differ`` deliberately compares only the keys a payload
    carries, so the plan an approver reads describes exactly this behaviour.
    """
    page.status = PageStatus(payload["status"])
    for field in PAGE_FIELDS:
        if field in payload:
            setattr(page, field, payload[field])
    for field in _DATETIME_FIELDS:
        raw = payload.get(field)
        setattr(page, field, datetime.fromisoformat(raw) if raw else None)
