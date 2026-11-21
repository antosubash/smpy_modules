"""An event's texts: one per content locale, written together with the event.

* every key must be a content locale (``unknown_locale``); the default locale
  (the first) is required on create and can never be deleted, nor left out of a
  PATCH that names texts (``default_locale_required``);
* a PATCH replaces each locale it names and ``null`` deletes that locale's text;
  the locales it leaves out are untouched;
* a slug is unique per ``(tenant, locale)`` across the trash. An absent slug is
  derived from the title and deduplicated within the language; one that is taken
  is ``slug_taken``. A rename records a redirect in that language only, and a
  claimed slug releases any redirect on it;
* the description is cleaned by the allow-list sanitiser here, at save.

Every mutation runs inside a savepoint opened *before* the first change
(:func:`~sm_events.calendar.slugs.slug_write`), so losing a race on the slug
index is a 409 and never leaves the request's transaction aborted.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select

from sm_events.calendar.slugs import free_text_slug, slug_write, slugify, text_slug_taken
from sm_events.content.redirects import record_rename, release_slug
from sm_events.content.richtext import clean
from sm_events.core import constants
from sm_events.core.errors import (
    DefaultLocaleRequired,
    DescriptionTooLong,
    SlugTaken,
    UnknownLocale,
)
from sm_events.models import Event, EventText
from sm_events.models.event_text import TEXT_SLUG_CONSTRAINT
from sm_events.web.schemas.texts import TextIn

__all__ = ["apply_texts", "texts_of"]

_FIELDS = ("title", "summary", "seo_title", "seo_description", "noindex")


async def texts_of(
    db: Any, event_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, EventText]]:
    """``{event id: {locale: text}}`` in one query."""
    found: dict[uuid.UUID, dict[str, EventText]] = {event_id: {} for event_id in event_ids}
    if not event_ids:
        return found
    rows = await db.execute(select(EventText).where(EventText.event_id.in_(list(event_ids))))  # type: ignore[attr-defined]
    for row in rows.scalars():
        found[row.event_id][row.locale] = row
    return found


def _check(texts: Mapping[str, TextIn | None], locales: tuple[str, ...], creating: bool) -> None:
    default = locales[0]
    for locale in texts:
        if locale not in locales:
            raise UnknownLocale
    if creating and texts.get(default) is None:
        raise DefaultLocaleRequired
    if default in texts and texts[default] is None:
        raise DefaultLocaleRequired


async def _slug_for(
    db: Any, event: Event, locale: str, data: TextIn, held: EventText | None
) -> str:
    """The slug a text will carry. ``SlugTaken`` for an explicit one another
    event holds in ``locale``; a derived one is the first free."""
    if data.slug is not None:
        if (held is None or held.slug != data.slug) and await text_slug_taken(
            db, locale, data.slug, except_event=event.id
        ):
            raise SlugTaken(field=f"texts.{locale}.slug")
        return data.slug
    if held is not None:
        return held.slug  # a title change alone never moves the address
    base = slugify(data.title, constants.EVENT_SLUG_FALLBACK)
    return await free_text_slug(db, locale, base, except_event=event.id)


def _description(data: TextIn, locale: str) -> str:
    try:
        return clean(data.description)
    except DescriptionTooLong as exc:
        exc.field = f"texts.{locale}.description"
        raise


def _values(data: TextIn, slug: str, locale: str) -> dict[str, Any]:
    return {
        "slug": slug,
        "title": data.title,
        "summary": data.summary,
        "description": _description(data, locale),
        "seo_title": data.seo_title,
        "seo_description": data.seo_description,
        "noindex": data.noindex,
    }


async def apply_texts(
    db: Any,
    event: Event,
    texts: Mapping[str, TextIn | None],
    *,
    locales: tuple[str, ...],
    creating: bool,
) -> list[str]:
    """Write ``texts`` onto ``event``; the locales whose text changed."""
    _check(texts, locales, creating)
    held = (await texts_of(db, [event.id]))[event.id] if not creating else {}
    plan: list[tuple[str, TextIn | None, dict[str, Any] | None]] = []
    for locale, data in texts.items():
        if data is None:
            plan.append((locale, None, None))
            continue
        slug = await _slug_for(db, event, locale, data, held.get(locale))
        plan.append((locale, data, _values(data, slug, locale)))
    changed: list[str] = []
    async with slug_write(db, TEXT_SLUG_CONSTRAINT):
        for locale, data, values in plan:
            row = held.get(locale)
            if data is None or values is None:
                if row is not None:
                    await db.delete(row)
                    changed.append(locale)
                continue
            if row is None:
                db.add(EventText(event_id=event.id, locale=locale, **values))
                changed.append(locale)
            else:
                if any(getattr(row, f) != values[f] for f in (*_FIELDS, "description", "slug")):
                    changed.append(locale)
                old_slug = row.slug
                for name, value in values.items():
                    setattr(row, name, value)
                if old_slug != values["slug"]:
                    await record_rename(db, event_id=event.id, locale=locale, old_slug=old_slug)
            await release_slug(db, locale=locale, slug=values["slug"])
    return changed
