"""The links in a reminder: built from the host's configured origin, never from a request.

``base_url`` is the host's ``public_base_url``
(:func:`~sm_events.reminders.base_url.public_base_url`); a relative, missing or non-web one is
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
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sm_events.core import constants
from sm_events.core.web_urls import is_web_url
from sm_events.models import Calendar, Event, EventText

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


def _local_date(event: Event, start: datetime) -> str:
    try:
        zone = ZoneInfo(event.timezone)
    except Exception:  # an unknown zone name: the date in UTC is still a date
        zone = ZoneInfo("UTC")
    return start.astimezone(zone).date().isoformat()


def event_url(
    links: Links,
    *,
    event: Event,
    calendar: Calendar,
    texts: dict[str, EventText],
    lang: str,
    occurrence_start: datetime,
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
        return f"{origin}{constants.EDITOR_URL}/{event.id}"
    default = links.content_locales[0]
    locale_prefix = "" if text.locale == default else f"/{text.locale}"
    path = f"{locale_prefix}{links.prefix}/{quote(text.slug, safe='')}"
    if event.rrule:
        path += f"?date={_local_date(event, occurrence_start)}"
    return f"{origin}{path}"
