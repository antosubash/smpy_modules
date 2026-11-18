"""The leak harness's table: what is hidden, and every public surface (see ``test_leaks``).

Every public route is added to :func:`surfaces` in the commit that adds the route.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sm_events.web.endpoints.public import _urls

from tests.support.calendars import PublicFixture

HIDDEN = (
    "draft",
    "in_review",
    "scheduled",
    "internal",
    "private",
    "trashed",
    "calendar_trashed",
)
"""The names of :attr:`PublicFixture.hidden` the leak tests parametrize over."""

LOCALES = ("en", "de")
HIDDEN_CALENDARS = ("internal", "private", "trashed")

Url = Callable[[PublicFixture, str, str | None], str]


@dataclass(frozen=True)
class Surface:
    """One public address family. ``url(fx, locale, hidden)``: for ``kind="page"``, the
    address of the hidden event named ``hidden`` (a key of ``fx.hidden``); for
    ``kind="listing"``, the listing's address (``hidden`` is ``None``)."""

    name: str
    kind: Literal["page", "listing"]
    url: Url
    status: int = 200
    """What a listing answers (the 404's suggestions are listings that answer 404)."""


def event_page(fx: PublicFixture, locale: str, hidden: str | None) -> str:
    assert hidden is not None
    return _urls.event_path(fx.slug(fx.hidden[hidden], locale), locale)


def event_ics(fx: PublicFixture, locale: str, hidden: str | None) -> str:
    assert hidden is not None
    return _urls.event_ics_path(fx.slug(fx.hidden[hidden], locale), locale)


def _api_url(locale: str) -> str:
    return f"{_urls.api_path()}?start=2026-01-01T00:00:00Z&end=2026-12-31T00:00:00Z&locale={locale}"


def surfaces(fx: PublicFixture, locale: str) -> list[Surface]:
    """Every public surface. Later tasks add theirs here: the index, a calendar's page, the
    occurrences API, the sitemap, the 404's suggestions."""
    return [
        Surface("event page", "page", event_page),
        Surface("event ics", "page", event_ics),
        Surface("index", "listing", lambda f, loc, _: _urls.index_path(loc)),
        Surface("calendar page", "listing", lambda f, loc, _: _urls.calendar_path(f.pub.slug, loc)),
        Surface(
            "404 suggestions",
            "listing",
            lambda f, loc, _: _urls.event_path("no-such-event", loc),
            status=404,
        ),
        Surface("occurrences api", "listing", lambda f, loc, _: _api_url(loc)),
        Surface(
            "all calendars feed", "listing", lambda f, loc, _: _urls.calendar_ics_path(None, loc)
        ),
        Surface(
            "calendar feed", "listing", lambda f, loc, _: _urls.calendar_ics_path(f.pub.slug, loc)
        ),
    ]


def assert_absent(body: str, fx: PublicFixture, names: tuple[str, ...] = ()) -> None:
    """The hidden events' title, slug and UID appear nowhere in ``body``."""
    for name, event in fx.hidden.items():
        if names and name not in names:
            continue
        for locale in LOCALES:
            slug = fx.slugs.get(f"{event.id}:{locale}")
            assert slug is None or slug not in body, (name, locale, "slug")
        assert event.uid not in body, (name, "uid")
        assert fx.slugs[f"{event.id}:en"].title() not in body, (name, "title")
