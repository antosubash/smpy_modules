"""A series: its rule, the start the module requires, and its overrides (Rulings 23 and 24).

Everything goes through PR 2's own checks (``rrule.parse`` and ``validate``, ``times.to_span``,
``expand.is_occurrence``); dateutil never sees raw file text. What the allow-list refuses
(a sub-daily frequency, a part it does not know, ``COUNT`` over 730, a second ``RRULE``,
``RDATE``, ``EXRULE``) makes the item ``unsupported_rule``: dropping any of them would silently
change which dates the event has.

**A start that is not an occurrence of its rule is adjusted, not refused.** RFC 5545 counts that
``DTSTART`` as an extra first instance, PR 2 refuses the mismatch, and skipping would lose a whole
series over one stray date. The start moves to the first rule instance after it (same duration),
``COUNT`` drops by one, and the item is noted ``start_adjusted``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from itertools import islice
from zoneinfo import ZoneInfo

from sm_events.calendar import rrule
from sm_events.calendar.expand import instances
from sm_events.calendar.times import Span, all_day_dates, localize, to_local, to_span
from sm_events.core import constants
from sm_events.core.errors import InvalidRule, InvalidTimes
from sm_events.feeds.importing.model import MappedOverride
from sm_events.feeds.importing.scan import Prop, RawEvent
from sm_events.feeds.importing.values import ItemSkip, When, read_instants, read_when
from sm_events.web.schemas.events_in import TimesIn

__all__ = ["Series", "map_series"]

_COUNT = re.compile(r"COUNT=\d+")
_TIME_CODES = (constants.END_BEFORE_START_CODE, constants.DURATION_TOO_LONG_CODE)
_COMPARED = ("SUMMARY", "LOCATION", "DESCRIPTION")


@dataclass(frozen=True)
class Series:
    times: TimesIn
    rrule: str | None
    overrides: list[MappedOverride]
    notes: tuple[str, ...]
    orphans: tuple[RawEvent, ...]
    """Children that match no occurrence of a series, for the mapper to report."""


def _span(times: TimesIn, *, recurring: bool) -> Span:
    try:
        return to_span(
            all_day=times.all_day,
            timezone=times.timezone,
            start=times.start,
            end=times.end,
            recurring=recurring,
        )
    except InvalidTimes as exc:
        raise ItemSkip(exc.code if exc.code in _TIME_CODES else "invalid_times") from None


def _adjust(rule: rrule.Rule, span: Span, times: TimesIn) -> tuple[TimesIn, str | None]:
    """The start moved to the first rule instance after it, and the rule text for what is left
    (``None``: a one-off). ``ItemSkip`` when the rule has no instance after the start."""
    tz = ZoneInfo(times.timezone)
    first = rrule.local_start(span, tz, all_day=times.all_day)
    bound = rrule.until_local(rule, tz) or rrule.add_years(first, constants.RRULE_MAX_YEARS)
    hit = next(
        (
            h
            for h in rrule.iterate(rule, dtstart_local=first, lower_local=first, until_local=bound)
            if h > first
        ),
        None,
    )
    if hit is None:
        raise ItemSkip("unsupported_rule")
    if times.all_day:
        old_first, after = all_day_dates(span, times.timezone)
        begin = localize(datetime.combine(hit.date(), time.min), tz)
        finish = localize(datetime.combine(hit.date() + (after - old_first), time.min), tz)
        moved = Span(begin, finish)
    else:
        begin = localize(hit, tz)
        moved = Span(begin, begin + (span.ends_at - span.starts_at))
    start, end = to_local(moved, all_day=times.all_day, timezone=times.timezone)
    adjusted = TimesIn(all_day=times.all_day, timezone=times.timezone, start=start, end=end)
    if rule.count is None:
        return adjusted, rule.text
    if rule.count - 1 < 2:
        return adjusted, None
    return adjusted, _COUNT.sub(f"COUNT={rule.count - 1}", rule.text)


def _occurrences(
    rule: rrule.Rule, span: Span, times: TimesIn, until: datetime | None, wanted: list[datetime]
) -> set[datetime]:
    """The starts of the rule's occurrences up to the latest date asked about, expanded **once**
    (at most ``IMPORT_EXPAND_CAP`` of them), to look dates up in. A date past the cap is not in
    the set: it cannot be verified, so it is ignored, never guessed."""
    if not wanted:
        return set()
    walk = instances(
        rule=rule,
        span=span,
        all_day=times.all_day,
        timezone=times.timezone,
        window_start=span.starts_at,
        window_end=max(wanted) + timedelta(seconds=1),
        recurrence_until=until,
    )
    return {i.original_start for i in islice(walk, constants.IMPORT_EXPAND_CAP)}


def _exdates(props: list[Prop], times: TimesIn) -> list[datetime]:
    if sum(len(p.value.split(",")) for p in props) > constants.IMPORT_MAX_EXDATES:
        raise ItemSkip("too_many_overrides")
    found: list[datetime] = []
    for prop in props:
        found.extend(read_instants(prop, tz=times.timezone, all_day=times.all_day))
    return found


def _child(child: RawEvent, times: TimesIn, calendar_tz: str) -> MappedOverride | None:
    """One ``RECURRENCE-ID`` child as an override, or ``None`` to drop it (noted)."""
    recurrence = next((p for p in child.props if p.name == "RECURRENCE-ID"), None)
    if recurrence is None or recurrence.params.get("RANGE", "").upper() == "THISANDFUTURE":
        return None
    try:
        (original,) = read_instants(recurrence, tz=times.timezone, all_day=times.all_day)
    except (ItemSkip, ValueError):
        return None
    status = next((p.value.strip().upper() for p in child.props if p.name == "STATUS"), "")
    if status == "CANCELLED":
        return MappedOverride(original_start=original, kind="cancelled")
    try:
        moved = read_when(child.props, calendar_tz=calendar_tz, into=times.timezone)
        if moved.all_day != times.all_day:
            return None
        _span(
            TimesIn(
                all_day=moved.all_day, timezone=times.timezone, start=moved.start, end=moved.end
            ),
            recurring=True,
        )
    except ItemSkip:
        return None
    return MappedOverride(original_start=original, kind="moved", start=moved.start, end=moved.end)


def _differs(master: list[Prop], child: RawEvent) -> bool:
    for name in _COMPARED:
        theirs = next((p.value for p in child.props if p.name == name), None)
        mine = next((p.value for p in master if p.name == name), None)
        if theirs is not None and theirs != mine:
            return True
    return False


def map_series(
    props: list[Prop], children: list[RawEvent], when: When, *, calendar_tz: str
) -> Series:
    """The schedule, rule and overrides of one master. ``ItemSkip`` with the reason when the item
    cannot be imported."""
    names = [p.name for p in props]
    rules = [p for p in props if p.name == "RRULE"]
    if len(rules) > 1 or "RDATE" in names or "EXRULE" in names:
        raise ItemSkip("unsupported_rule")
    times = TimesIn(all_day=when.all_day, timezone=when.timezone, start=when.start, end=when.end)
    exdates = [p for p in props if p.name == "EXDATE"]
    if not rules:
        _span(times, recurring=False)
        notes = ("exdate_ignored",) if exdates else ()
        return Series(times, None, [], notes, tuple(children))
    try:
        rule = rrule.parse(rules[0].value.strip(), all_day=times.all_day, timezone=times.timezone)
    except InvalidRule:
        raise ItemSkip("unsupported_rule") from None
    span = _span(times, recurring=True)
    notes: list[str] = []
    text: str | None = rule.text
    try:
        until = rrule.validate(rule, span, all_day=times.all_day, timezone=times.timezone)
    except InvalidRule as exc:
        if exc.code != constants.START_NOT_IN_RULE_CODE:
            raise ItemSkip("unsupported_rule") from None
        times, text = _adjust(rule, span, times)
        notes.append("start_adjusted")
        if text is None:
            return Series(times, None, [], tuple(notes), tuple(children))  # a one-off now
        span = _span(times, recurring=True)
        try:
            rule = rrule.parse(text, all_day=times.all_day, timezone=times.timezone)
            until = rrule.validate(rule, span, all_day=times.all_day, timezone=times.timezone)
        except InvalidRule:
            raise ItemSkip("unsupported_rule") from None
    if (
        len(children) + sum(len(p.value.split(",")) for p in exdates)
        > constants.IMPORT_MAX_OVERRIDES
    ):
        raise ItemSkip("too_many_overrides")

    exdate_values: list[datetime] = []
    try:
        exdate_values = _exdates(exdates, times)
    except ItemSkip as skip:
        if skip.code == "too_many_overrides":
            raise
        notes.append("exdate_ignored")
    pairs = [(child, _child(child, times, calendar_tz)) for child in children]
    wanted = [*exdate_values, *(o.original_start for _c, o in pairs if o is not None)]
    real = _occurrences(rule, span, times, until, wanted)
    found: dict[datetime, MappedOverride] = {}
    for instant in exdate_values:
        if instant in real:
            found[instant] = MappedOverride(original_start=instant, kind="skipped")
        elif "exdate_ignored" not in notes:
            notes.append("exdate_ignored")
    for child, override in pairs:
        if override is None or override.original_start not in real:
            if "override_dropped" not in notes:
                notes.append("override_dropped")
            continue
        found[override.original_start] = override  # a child beats an EXDATE for the same instant
        if _differs(props, child) and "override_fields_dropped" not in notes:
            notes.append("override_fields_dropped")
    return Series(
        times, text, sorted(found.values(), key=lambda o: o.original_start), tuple(notes), ()
    )
