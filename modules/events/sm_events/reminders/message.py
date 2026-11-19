"""The reminder mail: built from what the recipient may see *now*, as text and as HTML.

The caller hands in the event, its texts and its calendar as just re-read through the recipient's
own principal (never anything stored with the follow but the language), so nothing here can show
what the recipient may no longer see. The mail carries the event's title, time (in **its** zone,
named), place, the online link for an online or hybrid event, a note when this occurrence was
moved, a link to the event and one to the reminders page (sign-in required: no token), and a footer
naming the site. It carries nothing about anyone else, and no tracking: no pixel, no image, no
redirect link.

The text part fills a ``string.Template``; the HTML part is a Jinja template with autoescape on,
so every value is escaped by the engine and no HTML is ever assembled by hand. A title or place
is reduced to one line without control, direction or line-separator characters before it is used
anywhere, the subject doubly so (``clean_subject``). Only ``http(s)`` links without credentials are
ever shown.
"""

from __future__ import annotations

import importlib.resources
import re
from collections.abc import Mapping
from datetime import datetime
from functools import cache
from string import Template
from typing import Any

from jinja2 import Environment, FileSystemLoader
from simple_module_core.mail import MailMessage

from sm_events.core.constants.reminders_limits import REMINDER_LEADS, REMINDER_SUBJECT_MAX
from sm_events.core.text_safety import strip_unsafe
from sm_events.core.web_urls import is_web_url
from sm_events.models import Calendar, Event, EventText
from sm_events.reminders import formatting, strings
from sm_events.reminders import links as link_builder
from sm_events.web.services.events_out import pick_title

__all__ = ["build_message", "clean_subject"]

_SPACE = re.compile(r"\s+")
_ONLINE_MODES = ("online", "hybrid")


def _one_line(value: str | None) -> str:
    return strip_unsafe(_SPACE.sub(" ", value or "")).strip()


def clean_subject(value: str) -> str:
    """One line: whitespace collapsed, control, direction and separator characters gone, at most
    :data:`~sm_events.core.constants.reminders_limits.REMINDER_SUBJECT_MAX` characters."""
    return _one_line(value)[:REMINDER_SUBJECT_MAX].strip()


@cache
def _template_dir() -> str:
    return str(importlib.resources.files("sm_events.reminders") / "templates")


@cache
def _html() -> Environment:
    return Environment(loader=FileSystemLoader(_template_dir()), autoescape=True, trim_blocks=False)


@cache
def _text() -> Template:
    path = importlib.resources.files("sm_events.reminders") / "templates" / "reminder.txt"
    return Template(path.read_text(encoding="utf-8"))


def _lead_text(lead: int, loc: str) -> str:
    return strings.text(
        f"lead_{lead}" if lead in REMINDER_LEADS else "lead_other", loc, minutes=lead
    )


def build_message(
    *,
    to: str,
    event: Event,
    texts: Mapping[str, EventText],
    calendar: Calendar,
    occurrence_start: datetime,
    occurrence_end: datetime,
    lead: int,
    locale: str,
    default_locale: str,
    links: link_builder.Links,
    moved_from: datetime | None = None,
) -> MailMessage:
    """The mail for one occurrence. ``ValueError`` for an event that may not be reminded (not
    published, or cancelled) and for an unusable public base URL: a bug in the caller, never a
    message sent anyway."""
    if event.status != "published" or event.cancelled:
        raise ValueError("only a published, uncancelled event is reminded")
    loc = strings.catalogue_locale(locale)
    title, lang = pick_title(dict(texts), locale, loc, default_locale)  # type: ignore[arg-type]
    title = _one_line(title)
    when = formatting.format_when(
        start=occurrence_start,
        end=occurrence_end,
        all_day=event.all_day,
        timezone=event.timezone,
        locale=loc,
    )
    address = ", ".join(p.strip() for p in (event.address or "").splitlines() if p.strip())
    place = _one_line(", ".join(p for p in (event.venue_name, address) if p))
    place_lines = [strings.text("where", loc, place=place)] if place else []
    if event.attendance_mode in _ONLINE_MODES and event.online_url and is_web_url(event.online_url):
        place_lines.append(strings.text("online", loc, url=event.online_url))
    moved_line = ""
    if moved_from is not None and moved_from != occurrence_start:
        original = formatting.format_when(
            start=moved_from,
            end=moved_from,
            all_day=event.all_day,
            timezone=event.timezone,
            locale=loc,
        )
        moved_line = strings.text("moved", loc, original=original)
    event_link = link_builder.event_url(
        links,
        event=event,
        calendar=calendar,
        texts=dict(texts),
        lang=lang,
        occurrence_start=occurrence_start,
    )
    manage_link = link_builder.manage_url(links)
    site = links.origin().split("://", 1)[1]
    values: dict[str, Any] = {
        "intro": strings.text("intro", loc, lead=_lead_text(lead, loc)),
        "title": title,
        "when_line": strings.text("when", loc, when=when),
        "place_lines": place_lines,
        "moved_line": moved_line,
        "open_label": strings.text("open", loc),
        "manage_label": strings.text("manage", loc),
        "event_url": event_link,
        "manage_url": manage_link,
        "footer": strings.text("footer", loc, site=site),
        "lang": loc,
    }
    details = "\n".join(
        [title, values["when_line"], *place_lines, *([moved_line] if moved_line else [])]
    )
    text = _text().safe_substitute({**values, "details": details})
    html = _html().get_template("reminder.html").render(**values)
    subject = clean_subject(
        strings.text(
            "subject",
            loc,
            title=title,
            date=formatting.short_date(occurrence_start, timezone=event.timezone, locale=loc),
        )
    )
    return MailMessage(to=to, subject=subject, text=text, html=html)
