"""Turning news rows into bundle documents and back (#80).

Kept apart from capture and apply for the reason pagebuilder keeps
``PAGE_FIELDS`` apart: this list is what drifts when ``NewsArticle`` grows a
column, and a reviewer should see the whole of it at once.

Not carried, on purpose: ``id`` and every foreign key (host-local), the
``AuditMixin`` columns (``created_by``/``updated_by`` are this host's user ids,
the timestamps this host's history), ``rejection_note`` (a workflow artefact,
not content), ``deleted_at`` (trashed articles are never captured) and the
revision history, which stays on the host that wrote it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from news import locales
from news.constants import MAX_LOCALE_LEN
from news.models import ArticleStatus, NewsArticle
from news.naive_utc import as_utc

ArticleKey = tuple[str, str]
"""``(locale, slug)`` — an article's identity inside a bundle, as for pages."""

ARTICLES_DIR = "articles"
CATEGORIES_NAME = "categories.json"
TAGS_NAME = "tags.json"
REDIRECTS_NAME = "redirects.json"
TAG_REDIRECTS_NAME = "tag_redirects.json"

ARTICLE_FIELDS: tuple[str, ...] = (
    "translation_group",
    "title",
    "draft_data",
    "published_data",
    "meta_description",
    "og_image",
    "canonical_url",
    "index_in_search",
    "json_ld",
    "category",
    "pinned",
    "show_in_feed",
    "author",
)
"""Authored columns carried verbatim. ``translation_group`` because it is the
only thing tying an article to its translations."""

MEDIA_FIELDS: tuple[str, ...] = ("draft_data", "published_data", "og_image", "json_ld")
"""Fields that can hold a media-library URL, carried as ``asset://`` sentinels."""

DATETIME_FIELDS: tuple[str, ...] = ("published_at", "publish_at", "unpublish_at")
"""Instants, carried as ISO-8601 strings in UTC because JSON has no datetime."""

_LOCALE_PATTERN = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})*$")


def normalise_locale(raw: Any) -> str | None:
    """A bundle's language tag as this host stores it, or ``None`` if unreadable.

    A language this site publishes comes back in its configured spelling, so
    ``DE`` and ``de`` cannot become two articles. A well-formed tag it does not
    publish is kept: the article is inert until the language is configured, but
    it is still the site's content — the same rule pagebuilder's pages follow.
    """
    if not isinstance(raw, str):
        return None
    resolved = locales.resolve(raw)
    if resolved is not None:
        return resolved
    tag = raw.strip().lower()
    if tag and len(tag) <= MAX_LOCALE_LEN and _LOCALE_PATTERN.match(tag):
        return tag
    return None


def doc_key(doc: dict[str, Any]) -> ArticleKey:
    """The ``(locale, slug)`` a validated article document claims."""
    locale = normalise_locale(doc.get("locale"))
    assert locale is not None, "validated documents carry a readable locale"
    return locale, doc["slug"]


def name_key(name: str) -> str:
    """A category or tag name as the admin compares it: trimmed, case-insensitive.

    The rule ``category_service.find_by_name`` and ``tag_service`` apply, so a
    restore cannot create two rows the admin would call one.
    """
    return name.strip().lower()


def _segment(value: str) -> str:
    return value.replace("/", "_").replace("\\", "_")


def article_filename(slug: str, locale: str) -> str:
    """``<slug>.json`` in the default language, ``<locale>__<slug>.json`` otherwise.

    The same rule as ``pages/``. The document, not the name, is the truth.
    """
    stem = _segment(slug)
    if locales.is_default(locale):
        return f"{ARTICLES_DIR}/{stem}.json"
    return f"{ARTICLES_DIR}/{_segment(locale)}__{stem}.json"


IN_BATCH = 500
"""Ids per ``IN (...)``: well under every driver's bound-parameter limit."""


def batches(ids: list[int]) -> Iterator[list[int]]:
    """*ids* in slices an ``IN`` clause can carry (asyncpg stops at 32767 parameters)."""
    for start in range(0, len(ids), IN_BATCH):
        yield ids[start : start + IN_BATCH]


def _instant(value: datetime | None) -> str | None:
    """*value* as an ISO string in UTC, so equal instants spell equally whatever their offset."""
    value = as_utc(value)
    return value.astimezone(UTC).isoformat() if value is not None else None


def parse_instant(raw: Any) -> datetime | None:
    return as_utc(datetime.fromisoformat(raw)) if raw else None


def article_doc(article: NewsArticle, tags: list[str]) -> dict[str, Any]:
    """*article* as a document, with raw (host) URLs; the caller makes them portable."""
    doc: dict[str, Any] = {
        "slug": article.slug,
        "locale": article.locale,
        "status": ArticleStatus(article.status).value,
        "tags": sorted(tags),
    }
    for field in ARTICLE_FIELDS:
        doc[field] = getattr(article, field)
    for field in DATETIME_FIELDS:
        doc[field] = _instant(getattr(article, field))
    return doc


def comparable(doc: dict[str, Any]) -> dict[str, Any]:
    """*doc* with its instants normalised, so two spellings of one instant compare equal."""
    out = dict(doc)
    for field in DATETIME_FIELDS:
        if field in out:
            out[field] = _instant(parse_instant(out[field]))
    return out


def write_article(article: NewsArticle, doc: dict[str, Any]) -> None:
    """Write *doc* (URLs already resolved) onto *article*. Never its locale.

    Only the keys the document carries, so an absent field keeps the live
    value — the plan compares the same keys, so it describes this write.
    ``locale`` is set once, by the caller, when it creates the row: an
    article's language is fixed for its lifetime.
    """
    if "status" in doc:
        article.status = ArticleStatus(doc["status"])
        article.rejection_note = None  # not carried; a stale banner must not outlive the content
    for field in ARTICLE_FIELDS:
        # A document without a group keeps the row's own (a new row has one).
        if field in doc and not (field == "translation_group" and not doc[field]):
            setattr(article, field, doc[field])
    for field in DATETIME_FIELDS:
        if field in doc:
            setattr(article, field, parse_instant(doc[field]))
    article.slug = doc["slug"]
    article.deleted_at = None  # restoring content onto a trashed row revives it


def identity(article: NewsArticle) -> dict[str, Any]:
    """What the import's audit row names an article by: id *and* birth.

    An id alone is reused after a purge on SQLite, as for pages.
    """
    return {"id": article.id, "created_at": _instant(article.created_at)}
