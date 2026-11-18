"""The event card: when, where, the page link and an "Add to calendar" link.

**When** is formatted in the event's own timezone (``props.timezone``, never the reader's)
and in the render's language (``ctx.locale``: the host's default language, the same as the
footer's; a campaign has no language of its own). The zone is named by its tzdata
abbreviation (``CEST``), untranslated: Babel's short names are missing for most zones in
English, and a mail must name the zone the same way for every reader.

Every value is the snapshot's and goes through ``inert``; every address is made absolute
against the campaign tenant's public origin. The event's id (``source_id``) is never printed.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from babel import Locale, UnknownLocaleError
from babel.dates import format_date, format_time

from sm_newsletter.content.blocks import EventCardProps
from sm_newsletter.content.render import html as h
from sm_newsletter.content.render import styles as s
from sm_newsletter.content.render import text as t
from sm_newsletter.content.render.types import RenderContext
from sm_newsletter.content.urls import absolute

_FALLBACK = "en"
_SPACES = str.maketrans({"\u202f": " ", "\u00a0": " "})  # CLDR's narrow no-break spaces
_BIDI = re.compile("[\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069]")
_ONE_DAY = timedelta(days=1)
_CONTENT_WIDTH = s.WIDTH - 64
_DOT = " · "
_EN = "\u2013"  # an en dash
_DASH = f" {_EN} "


def strip_bidi(value: str) -> str:
    """``value`` without direction marks, embeddings, overrides and isolates: they would reorder
    the text around them in a mail client. Events refuses them in a title, but a snapshot may hold
    text from before that, so the renderer neutralises them itself."""
    return _BIDI.sub("", value)


def _locale(name: str) -> Locale:
    try:
        return Locale.parse(name.replace("-", "_"))
    except (UnknownLocaleError, ValueError):
        return Locale.parse(_FALLBACK)


def _day(value: date, locale: Locale) -> str:
    return format_date(value, "full", locale=locale).translate(_SPACES)


def _time(value: datetime, locale: Locale) -> str:
    return format_time(value, "short", locale=locale).translate(_SPACES)


def when(p: EventCardProps, locale: str) -> str:
    """The date and time of the card in the event's zone and ``locale``'s language."""
    loc = _locale(locale)
    if p.all_day and p.start_date and p.end_date:
        first, last = p.start_date, p.end_date - _ONE_DAY
        return _day(first, loc) if last <= first else f"{_day(first, loc)}{_DASH}{_day(last, loc)}"
    zone = ZoneInfo(p.timezone)
    begin, end = p.starts_at.astimezone(zone), p.ends_at.astimezone(zone)
    zone_begin, zone_end = begin.tzname() or p.timezone, end.tzname() or p.timezone
    if begin.date() == end.date():
        if zone_begin == zone_end:
            span = f"{_time(begin, loc)}{_EN}{_time(end, loc)} {zone_end}"
        else:
            span = f"{_time(begin, loc)} {zone_begin}{_EN}{_time(end, loc)} {zone_end}"
        return f"{_day(begin.date(), loc)}, {span}"
    return (
        f"{_day(begin.date(), loc)}, {_time(begin, loc)} {zone_begin}{_DASH}"
        f"{_day(end.date(), loc)}, {_time(end, loc)} {zone_end}"
    )


def place_line(p: EventCardProps, online: str) -> str:
    """The venue for an in-person event, ``online`` for an online one, both for a hybrid."""
    if p.attendance_mode == "online":
        return online
    if p.attendance_mode == "hybrid":
        return _DOT.join(part for part in (p.place, online) if part)
    return p.place


def html(p: EventCardProps, ctx: RenderContext) -> str:
    href = h.url(ctx.content_base, p.url)
    copy = ctx.footer
    title, excerpt = strip_bidi(p.title), strip_bidi(p.excerpt)
    out = ""
    if p.image_url:
        out += (
            f'<a href="{href}"><img src="{h.url(ctx.content_base, p.image_url)}"'
            f' width="{_CONTENT_WIDTH}" alt="{h.inert(title)}"'
            f' style="{s.fluid_image(_CONTENT_WIDTH)}"></a>'
        )
    if p.cancelled:
        out += f'<p style="{s.CARD_BADGE}">{h.inert(copy.cancelled)}</p>'
    if title:
        title_link = f"color:{s.TEXT_COLOR};text-decoration:none"
        out += (
            f'<h3 style="{s.CARD_TITLE}">'
            f'<a href="{href}" style="{title_link}">{h.inert(title)}</a></h3>'
        )
    for line in (when(p, ctx.locale), strip_bidi(place_line(p, copy.online))):
        if line:
            out += f'<p style="{s.CARD_META}">{h.inert(line)}</p>'
    if excerpt:
        out += f'<p style="{s.CARD_TEXT}">{h.inert(excerpt)}</p>'
    link = f"{s.CARD_LINK_BASE};{s.accent_link(ctx.branding.accent)}"
    out += f'<a href="{href}" style="{link}">{h.inert(copy.read_more)}</a>'
    if not p.cancelled:
        ics = h.url(ctx.content_base, p.ics_url)
        out += f' <span style="{s.CARD_SEP}">{_DOT.strip()}</span>'
        out += f' <a href="{ics}" style="{link}">{h.inert(copy.add_to_calendar)}</a>'
    return out


def text(p: EventCardProps, ctx: RenderContext) -> str:
    base, copy = ctx.content_base, ctx.footer
    title = t.inert(strip_bidi(p.title))
    if p.cancelled:
        title = f"{t.inert(copy.cancelled)}: {title}" if title else t.inert(copy.cancelled)
    lines = [
        title,
        t.inert(when(p, ctx.locale)),
        t.inert(strip_bidi(place_line(p, copy.online))),
        t.inert(strip_bidi(p.excerpt)),
        absolute(base, p.url),
    ]
    if not p.cancelled:
        lines.append(f"{t.inert(copy.add_to_calendar)}: {absolute(base, p.ics_url)}")
    return "\n".join(line for line in lines if line)
