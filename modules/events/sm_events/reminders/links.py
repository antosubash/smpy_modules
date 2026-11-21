"""The links in a reminder: built from the host's configured origin, never from a request.

``base_url`` is the host's ``public_base_url``
(:func:`~sm_events.core.host_settings.public_base_url`); a relative, missing or non-web one is
refused (``ValueError``) so a reminder is never sent with a link that points nowhere or somewhere
a visitor chose. ``availability`` already reports
``no_public_base_url`` before anything is built.

The event link is the **public page** only when the event is publicly visible (a published event
of a public calendar) and the host is single-tenant (on a multi-tenant host a tenant's public
origin is a property of the request, so there is none to build here); otherwise it is the console
link, which a signed-in viewer opens. The "manage reminders" link is the console's Reminders page:
it needs a sign-in, so it carries no token and no state change can be triggered by a mail
scanner fetching it. The public path is built from the stored ``public_prefix`` and content
locales the worker reads; a prefix the web process refused at boot (another module owns it) is the
one case where it can differ from the site's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

from sm_events.core import constants, locales
from sm_events.core.web_urls import is_web_url
from sm_events.models import Calendar, Event, EventText
from sm_events.reminders import formatting
from sm_events.web.endpoints.public import _urls

__all__ = ["Links", "event_url", "manage_url"]


@dataclass(frozen=True)
class Links:
    base_url: str
    prefix: str
    content_locales: tuple[str, ...]
    single_tenant: bool

    def origin(self) -> str:
        base = self.base_url.strip().rstrip("/")
        if not is_web_url(base):
            raise ValueError("no usable public base URL")
        return base


def manage_url(links: Links) -> str:
    return f"{links.origin()}{constants.REMINDERS_URL}"


def _calendar_path(
    event: Event, calendar: Calendar, occurrence_start: datetime, occurrence_key: str
) -> str:
    """The console calendar on that occurrence's day in the event's own zone, its detail open
    (read-only: the page takes ``event=<key>``), for someone who may see but not edit it."""
    day = occurrence_start.astimezone(formatting.zone_of(event.timezone)).date().isoformat()
    query = urlencode(
        {
            "view": "day",
            "date": day,
            "tz": "calendar",
            "calendar": str(calendar.id),
            "event": occurrence_key,
        }
    )
    return f"{constants.CALENDAR_URL}?{query}"


def event_url(
    links: Links,
    *,
    event: Event,
    calendar: Calendar,
    texts: dict[str, EventText],
    lang: str,
    occurrence_start: datetime,
    occurrence_key: str | None = None,
    can_edit: bool = False,
) -> str:
    origin = links.origin()
    public = (
        calendar.visibility == "public"
        and event.status == "published"
        and links.single_tenant
        and bool(links.content_locales)
    )
    text = texts.get(lang) if lang in links.content_locales else None
    text = text or texts.get(links.content_locales[0] if links.content_locales else "")
    if not public or text is None:
        if can_edit or occurrence_key is None:
            return f"{origin}{constants.EDITOR_URL}/{event.id}"
        return f"{origin}{_calendar_path(event, calendar, occurrence_start, occurrence_key)}"
    base = f"{locales.prefix_for(text.locale, links.content_locales[0])}{links.prefix}"
    day = (
        occurrence_start.astimezone(formatting.zone_of(event.timezone)).date()
        if event.rrule
        else None
    )
    return f"{origin}{_urls.build_event_path(text.slug, base=base, date=day)}"
