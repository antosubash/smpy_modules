"""Every way an article is created or changed.

Split from ``_articles.py`` when that file reached the repo's 300-line cap, on
the seam the package was already split along: a *request body* is a different
kind of thing from the shape a screen reads back. The read side keeps the file
named after the resource; these are the writes to it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from news.constants import (
    MAX_AUTHOR_LEN,
    MAX_CATEGORY_LEN,
    MAX_LOCALE_LEN,
    MAX_NOTE_LEN,
    MAX_SLUG_LEN,
    MAX_TITLE_LEN,
    MAX_URL_LEN,
    SLUG_PATTERN,
)
from news.display_date import as_display_date


class ArticleCreate(BaseModel):
    """Create an article.

    This used to be two DTOs and two requests: one that created a *page* and one
    that attached news metadata to it, which could only ever be half-done — a
    failure of the second stranded an empty, articleless page with nothing to
    clean it up, and the dialog had to remember the first request's id so a
    retry could adopt it. One table means one insert.

    ``slug`` is optional. Omitted, the server derives a free one from the title;
    supplied, it is used verbatim and a collision is a 409, because a URL the
    author typed should not be silently changed under them.
    """

    title: str = Field(min_length=1, max_length=MAX_TITLE_LEN)
    slug: str | None = Field(
        default=None, max_length=MAX_SLUG_LEN, pattern=SLUG_PATTERN
    )
    locale: str | None = Field(default=None, max_length=MAX_LOCALE_LEN)
    """Language to write in. ``None`` means the site's default.

    An article created this way starts a translation group of its own. Joining
    an existing one is ``POST /articles/{id}/translations``.
    """

    category: str = Field(default="", max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None
    author: str = Field(default="", max_length=MAX_AUTHOR_LEN)

    _display_date = field_validator("published_at")(as_display_date)
    """Truncate to the calendar day as sent — see ``news.display_date``."""


class ArticleTranslationCreate(BaseModel):
    """Start an article's counterpart in another language.

    A translation is a *sibling article* sharing a ``translation_group``, not a
    second body on one row — and not, as it was while the body lived on a
    pagebuilder page, a translation of that page performed on the article's
    behalf.

    Only the three things a translator decides. Category, byline, date, pin and
    feed membership are copied from the source rather than asked for again:
    they are facts about the story, not about the language it is told in, and a
    form that asked would invite them to drift apart between languages.
    """

    locale: str = Field(min_length=2, max_length=MAX_LOCALE_LEN)
    slug: str | None = Field(
        default=None, max_length=MAX_SLUG_LEN, pattern=SLUG_PATTERN
    )
    """Address within the new language. Defaults to the source article's own,
    which is free unless an unrelated article already took it — slugs are
    unique per language, so ``/news/x`` and ``/de/news/x`` do not collide."""

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LEN)
    """Defaults to the source's headline, i.e. untranslated — a more useful
    starting point for a translator than a blank field, and it makes what still
    needs doing obvious in the list."""


class ArticleUpdate(BaseModel):
    """The listing metadata, and the article's identity and SEO.

    Every field is optional and only the ones actually sent are applied, so the
    admin list's inline edit can send two fields without clearing the rest.
    Changing ``slug`` records a redirect from the old one, scoped to the
    article's language.

    Deliberately no ``locale``: an article's language is fixed for its
    lifetime. Moving one would strand its slug in the old language and orphan
    the redirect pointing at it — ``POST /articles/{id}/translations`` starts a
    sibling instead.
    """

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LEN)
    slug: str | None = Field(
        default=None, max_length=MAX_SLUG_LEN, pattern=SLUG_PATTERN
    )
    category: str | None = Field(default=None, max_length=MAX_CATEGORY_LEN)
    published_at: datetime | None = None
    pinned: bool | None = None
    show_in_feed: bool | None = None
    author: str | None = Field(default=None, max_length=MAX_AUTHOR_LEN)
    meta_description: str | None = Field(default=None, max_length=MAX_URL_LEN)
    og_image: str | None = Field(default=None, max_length=MAX_URL_LEN)
    canonical_url: str | None = Field(default=None, max_length=MAX_URL_LEN)
    index_in_search: bool | None = None
    json_ld: dict[str, Any] | None = None

    _display_date = field_validator("published_at")(as_display_date)
    """Truncate to the calendar day as sent — see ``news.display_date``."""


class ArticleBodyUpdate(BaseModel):
    """An autosave from the block canvas.

    Its own DTO, and its own endpoint, because it fires on a timer rather than
    on a person pressing something — so it must not be able to reach the slug,
    the status, or anything else a rename would record a redirect for.
    """

    draft_data: dict[str, Any] = Field(default_factory=dict)


class RejectRequest(BaseModel):
    note: str | None = Field(default=None, max_length=MAX_NOTE_LEN)


class ScheduleRequest(BaseModel):
    """When an article should go live, and when it should come down.

    Both fields are three-valued and the endpoint passes only what was actually
    sent: omitted leaves the column alone, an instant sets it, and an explicit
    ``null`` clears it. Cancelling a schedule has to be expressible, and is not
    the same as declining to mention one.

    Neither is truncated to a calendar day, unlike ``published_at``. That is a
    display date and the day is the whole of it; these are instants, and an
    embargo that lifts "some time on Tuesday" is not an embargo.
    """

    publish_at: datetime | None = None
    unpublish_at: datetime | None = None
