"""Checking an uploaded ``news/`` section before the bundle is accepted (#80).

Everything apply would trip over is refused here, as a 422 naming the file:
a wrong type, a value longer than its column, an unknown status, a language
tag that is not one, two documents claiming one address or one translation
slot, a tag the bundle does not list, a duplicate redirect, and media the
bundle does not carry. Synchronous and database-free: it runs in pagebuilder's
extraction thread. Reading goes through ``ctx.read_json``, which refuses any
name that leaves the section's directory.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pagebuilder.contracts.bundle import ValidateContext

from news.constants import (
    MAX_AUTHOR_LEN,
    MAX_CATEGORY_LEN,
    MAX_SLUG_LEN,
    MAX_TAG_LEN,
    MAX_TITLE_LEN,
    MAX_TRANSLATION_GROUP_LEN,
    MAX_URL_LEN,
    SLUG_PATTERN,
)
from news.integrations.bundle.documents import (
    ARTICLES_DIR,
    CATEGORIES_NAME,
    DATETIME_FIELDS,
    MEDIA_FIELDS,
    REDIRECTS_NAME,
    TAG_REDIRECTS_NAME,
    TAGS_NAME,
    name_key,
    normalise_locale,
)
from news.models import ArticleStatus

_STATUSES = frozenset(s.value for s in ArticleStatus)
_INT_MIN, _INT_MAX = -(2**31), 2**31 - 1
"""The range of an ``INTEGER`` column on every database news runs on."""


def _integer(value: Any) -> bool:
    """An ``int`` the column can store — a larger one would fail at approval, not here."""
    return isinstance(value, int) and not isinstance(value, bool) and _INT_MIN <= value <= _INT_MAX


def _name(limit: int) -> Callable[[Any], bool]:
    """A category or tag name: within the column, and not blank once trimmed."""
    return lambda v: isinstance(v, str) and len(v) <= limit and bool(name_key(v))


_SLUG = re.compile(SLUG_PATTERN)


def _slug(value: Any) -> bool:
    """An article address as the editor would accept it, which is also a safe file name."""
    return isinstance(value, str) and len(value) <= MAX_SLUG_LEN and bool(_SLUG.match(value))


def _text(limit: int, *, empty: bool = True) -> Callable[[Any], bool]:
    return lambda v: isinstance(v, str) and len(v) <= limit and (empty or bool(v))


def _optional(check: Callable[[Any], bool]) -> Callable[[Any], bool]:
    return lambda v: v is None or check(v)


def _instant(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _flag(value: Any) -> bool:
    return isinstance(value, bool)


_ARTICLE_RULES: dict[str, Callable[[Any], bool]] = {
    "slug": _slug,
    "title": _text(MAX_TITLE_LEN),
    "translation_group": _optional(_text(MAX_TRANSLATION_GROUP_LEN, empty=False)),
    "draft_data": lambda v: isinstance(v, dict),
    "published_data": _optional(lambda v: isinstance(v, dict)),
    "status": lambda v: v in _STATUSES,
    "meta_description": _optional(_text(MAX_URL_LEN)),
    "og_image": _optional(_text(MAX_URL_LEN)),
    "canonical_url": _optional(_text(MAX_URL_LEN)),
    "index_in_search": _flag,
    "json_ld": _optional(lambda v: isinstance(v, dict)),
    "category": _text(MAX_CATEGORY_LEN),
    "pinned": _flag,
    "show_in_feed": _flag,
    "author": _text(MAX_AUTHOR_LEN),
    **dict.fromkeys(DATETIME_FIELDS, _instant),
    "tags": lambda v: isinstance(v, list) and all(isinstance(t, str) for t in v),
}
_REQUIRED = frozenset({"slug", "locale", "title", "status"})


def _list(ctx: ValidateContext, name: str, fields: dict[str, Callable[[Any], bool]]) -> list:
    """A JSON list of objects whose *fields* all pass, or an empty one if absent."""
    if not (ctx.dir / name).is_file():
        return []
    rows = ctx.read_json(name)
    if not isinstance(rows, list):
        raise ctx.invalid(f"news/{name} is not a list")
    for row in rows:
        if not isinstance(row, dict) or not all(check(row.get(f)) for f, check in fields.items()):
            raise ctx.invalid(f"news/{name} has a malformed entry: {row!r:.120}")
    return rows


def _unique(ctx: ValidateContext, name: str, rows: list, *keys: str) -> None:
    for key in keys:
        seen: set[Any] = set()
        for row in rows:
            value = tuple(row.get(k) for k in key.split("+"))
            if value in seen:
                raise ctx.invalid(f"news/{name} lists {'/'.join(map(str, value))} twice")
            seen.add(value)


def _unique_names(ctx: ValidateContext, name: str, rows: list) -> None:
    """Two names the admin would call one (``Updates`` and ``updates``) are refused."""
    seen: dict[str, str] = {}
    for row in rows:
        key = name_key(row["name"])
        if key in seen:
            raise ctx.invalid(
                f"news/{name} lists {seen[key]!r} and {row['name']!r}, which are the same name"
            )
        seen[key] = row["name"]


def _article(ctx: ValidateContext, relative: str) -> dict[str, Any]:
    doc = ctx.read_json(relative)
    where = f"news/{relative}"
    if not isinstance(doc, dict):
        raise ctx.invalid(f"{where} is not an article document")
    missing = sorted(_REQUIRED - doc.keys())
    if missing:
        raise ctx.invalid(f"{where} is missing {', '.join(missing)}")
    if normalise_locale(doc["locale"]) is None:
        raise ctx.invalid(f"{where} has an unreadable locale: {doc['locale']!r:.40}")
    for field, check in _ARTICLE_RULES.items():
        if field in doc and not check(doc[field]):
            raise ctx.invalid(f"{where} has an invalid {field}")
    for field in MEDIA_FIELDS:
        ctx.check_media(doc.get(field), f"article /{doc['slug']} ({doc['locale']})")
    return doc


def validate(ctx: ValidateContext) -> None:
    if not ctx.dir.is_dir():
        return
    categories = _list(
        ctx,
        CATEGORIES_NAME,
        {
            "name": _name(MAX_CATEGORY_LEN),
            "slug": _text(MAX_CATEGORY_LEN, empty=False),
            "position": _integer,
        },
    )
    _unique(ctx, CATEGORIES_NAME, categories, "name", "slug")
    _unique_names(ctx, CATEGORIES_NAME, categories)
    tag_rule = _text(MAX_TAG_LEN, empty=False)
    tags = _list(ctx, TAGS_NAME, {"name": _name(MAX_TAG_LEN), "slug": tag_rule})
    _unique(ctx, TAGS_NAME, tags, "name", "slug")
    _unique_names(ctx, TAGS_NAME, tags)
    redirects = _list(
        ctx,
        REDIRECTS_NAME,
        {
            "from_slug": _slug,
            "to_slug": _slug,
            "locale": lambda v: normalise_locale(v) is not None,
        },
    )
    for row in redirects:
        row["locale"] = normalise_locale(row["locale"])
    _unique(ctx, REDIRECTS_NAME, redirects, "locale+from_slug")
    tag_redirects = _list(ctx, TAG_REDIRECTS_NAME, {"from_slug": tag_rule, "to_slug": tag_rule})
    _unique(ctx, TAG_REDIRECTS_NAME, tag_redirects, "from_slug")

    directory = ctx.dir / ARTICLES_DIR
    names = sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []
    docs = [_article(ctx, f"{ARTICLES_DIR}/{name}") for name in names if name.endswith(".json")]
    for doc in docs:
        doc["locale"] = normalise_locale(doc["locale"])
    _unique(ctx, ARTICLES_DIR, docs, "locale+slug")
    grouped = [d for d in docs if d.get("translation_group")]
    _unique(ctx, ARTICLES_DIR, grouped, "translation_group+locale")
    known_tags = {t["name"] for t in tags}
    for doc in docs:
        unknown = sorted(set(doc.get("tags") or []) - known_tags)
        if unknown:
            raise ctx.invalid(
                f"article /{doc['slug']} ({doc['locale']}) is tagged {', '.join(unknown)}, "
                f"which news/{TAGS_NAME} does not list"
            )
