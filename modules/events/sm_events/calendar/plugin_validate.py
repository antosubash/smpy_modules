"""A plugin's answer, checked and turned into the read's own :class:`Occurrence`.

Nothing a plugin returns is trusted. Any one invalid item rejects the **whole** answer
(:class:`InvalidPluginItem`): a partly valid answer comes from a broken source, which is
the one most likely to leak. An item that merely lies outside the window is dropped,
because a source may over-fetch at the edges. The fields the plugin does not choose are
filled in here: the source id (so it cannot claim another's), the calendar being read,
``editable=False``, the built-in type and no event id.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sm_events.calendar.extension_types import SourceCalendar, SourceOccurrence
from sm_events.calendar.occurrence import PluginOccurrence
from sm_events.calendar.times import Span, localize, supported_instant
from sm_events.core import constants, timezones
from sm_events.web.schemas._fields import _BIDI, _INVISIBLE, _LINE_SEPARATORS

__all__ = ["InvalidPluginItem", "to_occurrences"]

INVALID_ITEM = "invalid_item"
DUPLICATE_KEY = "duplicate_key"

_HIDDEN = _BIDI | _LINE_SEPARATORS | _INVISIBLE
_LANG = re.compile(constants.PLUGIN_LANG_PATTERN)
_URL_FORBIDDEN = re.compile(r"[\x00-\x20\x7f-\x9f\\]")
_ONE_DAY = timedelta(days=1)


class InvalidPluginItem(Exception):  # noqa: N818 - a verdict on an answer, not an error type
    def __init__(self, code: str = INVALID_ITEM) -> None:
        super().__init__(code)
        self.code = code


def _title(raw: str) -> str:
    kept = "".join(
        " " if ch in "\n\r\t" else ch
        for ch in raw
        if ch in "\n\r\t" or (unicodedata.category(ch) != "Cc" and ch not in _HIDDEN)
    )
    text = kept.strip()
    if not text:
        raise InvalidPluginItem
    return text


def _url(raw: str | None) -> str | None:
    """``None``, a same-origin path, or an absolute ``http``/``https`` URL."""
    if raw is None:
        return None
    if not raw or len(raw) > constants.SOURCE_URL_MAX or _URL_FORBIDDEN.search(raw):
        raise InvalidPluginItem
    if raw.startswith("/"):
        if raw.startswith("//"):
            raise InvalidPluginItem
        return raw
    parts = urlsplit(raw)
    if parts.scheme.lower() not in constants.PLUGIN_URL_SCHEMES or not parts.netloc:
        raise InvalidPluginItem
    return raw


def _aware(value: datetime | None) -> bool:
    return value is not None and value.utcoffset() is not None


def _midnight(day: date, tz: ZoneInfo) -> datetime:
    return localize(datetime.combine(day, time.min), tz)


def _span(item: SourceOccurrence, tz_name: str) -> tuple[Span, date | None, date | None]:
    limit = timedelta(days=constants.MAX_EVENT_DAYS)
    if item.all_day:
        first, last = item.start_date, item.end_date
        if first is None or last is None or item.start is not None or item.end is not None:
            raise InvalidPluginItem
        if not first < last or last - first > limit:
            raise InvalidPluginItem
        tz = ZoneInfo(tz_name)
        return Span(_midnight(first, tz), _midnight(last, tz)), first, last
    begin, finish = item.start, item.end
    if begin is None or finish is None or item.start_date is not None or item.end_date is not None:
        raise InvalidPluginItem
    if begin.utcoffset() is None or finish.utcoffset() is None:
        raise InvalidPluginItem  # a naive time means nothing
    if not begin < finish or finish - begin > limit:
        raise InvalidPluginItem
    return Span(begin.astimezone(UTC), finish.astimezone(UTC)), None, None


def _one(
    item: Any, *, source_id: str, calendar: SourceCalendar, default_lang: str
) -> PluginOccurrence:
    if not isinstance(item, SourceOccurrence):
        raise InvalidPluginItem
    tz = item.timezone or calendar.default_timezone
    if not timezones.is_known(tz):
        raise InvalidPluginItem
    lang = item.lang or default_lang
    if not _LANG.match(lang):
        raise InvalidPluginItem
    span, first, last = _span(item, tz)
    supported_instant(span.starts_at)
    supported_instant(span.ends_at)
    return PluginOccurrence(
        source=source_id,
        key=item.key,
        calendar_id=calendar.id,
        start=span.starts_at,
        end=span.ends_at,
        all_day=item.all_day,
        timezone=tz,
        start_date=first,
        end_date=last,
        title=_title(item.title),
        lang=lang,
        color=item.color or calendar.color,
        url=_url(item.url),
        status=item.status,
        type=constants.BUILTIN_TYPE,
        editable=False,
        event_id=None,
        original_start=None,
        event_status=None,
        updated_at=item.updated_at.astimezone(UTC) if _aware(item.updated_at) else None,
    )


def to_occurrences(
    items: Sequence[Any],
    *,
    source_id: str,
    calendar: SourceCalendar,
    start: datetime,
    end: datetime,
    default_lang: str,
) -> list[PluginOccurrence]:
    """The valid items that intersect ``[start, end)``. Raises :class:`InvalidPluginItem`
    (``code`` ``invalid_item`` or ``duplicate_key``) when any item is not valid."""
    found: list[PluginOccurrence] = []
    keys: set[str] = set()
    for raw in items:
        try:
            occ = _one(raw, source_id=source_id, calendar=calendar, default_lang=default_lang)
        except InvalidPluginItem:
            raise
        except (ValueError, OverflowError, TypeError):  # a date or zone no arithmetic can hold
            raise InvalidPluginItem from None
        if occ.key in keys:
            raise InvalidPluginItem(DUPLICATE_KEY)
        keys.add(occ.key)
        if occ.start < end and occ.end > start:
            found.append(occ)
    return found
