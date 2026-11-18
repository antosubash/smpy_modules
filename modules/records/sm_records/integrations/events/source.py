"""``records:dates``: records with a date field, on an events calendar.

What a viewer sees is records' own rule (:mod:`sm_records.contracts.dated`): published, untrashed
records of a type they may read, never wider than records' list API; for the public, only types
that are ``is_public``. The item's link is the record's admin page for a signed-in viewer (who
may read the type, so may open it) and ``None`` for the public. The title is the record's display
title, as text. A date field gives an all-day item; a datetime field a timed one, an instant that
the calendar shows in its own zone.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sm_events.contracts.extensions import (
    SettingsContext,
    SourceContext,
    SourceError,
    SourceOccurrence,
)

from sm_records.contracts.dated import (
    MAX_DATED_BATCH,
    DatedCaller,
    DatedHit,
    DatedQueryError,
    dated_field_kind,
    dated_records,
)
from sm_records.core import constants
from sm_records.integrations.events.settings import (
    RecordDateMapping,
    RecordDatesSettings,
    caller_of,
    check_settings,
)

__all__ = ["RecordDatesSource"]

LOOKBACK_DAYS = 31
"""A multi-day record that started earlier still shows while it runs."""
SPAN_MAX_DAYS = 366
"""What events accepts for one item; a longer record is clipped, never refused."""
TITLE_MAX = 300
_REASON_CODES = {"reindexing": "reindexing"}
_ONE_DAY = timedelta(days=1)


def _window(
    kind_is_date: bool, ctx: SourceContext, start: datetime, end: datetime
) -> tuple[Any, Any]:
    back = timedelta(days=LOOKBACK_DAYS)
    if not kind_is_date:
        return start - back, end
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(ctx.calendar.default_timezone)
    first, last = start.astimezone(tz), end.astimezone(tz)
    hi = last.date() if last.time() == datetime.min.time() else last.date() + _ONE_DAY
    return first.date() - back, max(hi, first.date() + _ONE_DAY)


def _title(hit: DatedHit) -> str:
    return (hit.display_title.strip() or hit.type_key)[:TITLE_MAX]


def _item(hit: DatedHit, mapping: RecordDateMapping, ctx: SourceContext) -> SourceOccurrence:
    url = None if ctx.viewer is None else f"{constants.VIEW_PREFIX}/{hit.type_key}/{hit.uuid}"
    common: dict[str, Any] = {
        "key": f"{hit.type_key}:{hit.uuid}:{mapping.field}",
        "title": _title(hit),
        "url": url,
        "color": mapping.color,
        "timezone": ctx.calendar.default_timezone,
    }
    if not isinstance(hit.start, datetime):
        first = hit.start
        last = hit.end if isinstance(hit.end, date) and hit.end >= first else first
        last = min(last, first + timedelta(days=SPAN_MAX_DAYS - 1))
        return SourceOccurrence(all_day=True, start_date=first, end_date=last + _ONE_DAY, **common)
    begin = hit.start.astimezone(UTC)
    finish = hit.end.astimezone(UTC) if isinstance(hit.end, datetime) else None
    if finish is None or finish <= begin:
        finish = begin + timedelta(minutes=mapping.duration_minutes)
    finish = min(finish, begin + timedelta(days=SPAN_MAX_DAYS))
    return SourceOccurrence(start=begin, end=finish, **common)


class RecordDatesSource:
    id = "records:dates"
    label_key = "records.events.source.label"
    public = True
    color = None
    icon = "database"
    settings_model = RecordDatesSettings

    async def check_settings(self, sctx: SettingsContext, settings: RecordDatesSettings) -> None:
        await check_settings(sctx, settings)

    async def occurrences(
        self, ctx: SourceContext, start: datetime, end: datetime
    ) -> list[SourceOccurrence]:
        settings = ctx.settings
        assert isinstance(settings, RecordDatesSettings)
        caller = caller_of(ctx.viewer)
        wanted = ctx.limit + 1
        items: list[SourceOccurrence] = []
        for mapping in settings.mappings:
            if len(items) >= wanted:
                break
            kind = await dated_field_kind(
                ctx.db,
                tenant_id=ctx.tenant_id,
                type_key=mapping.type_key,
                field=mapping.field,
                caller=caller,
            )
            if kind is None:
                # No such type for this viewer (gone, or not theirs): nothing to show. A type
                # that is theirs whose field is no longer a date is told apart below.
                await self._field_still_there(ctx, caller, mapping)
                continue
            lo, hi = _window(kind == "date", ctx, start, end)
            try:
                page = await dated_records(
                    ctx.db,
                    tenant_id=ctx.tenant_id,
                    type_key=mapping.type_key,
                    field=mapping.field,
                    end_field=mapping.end_field,
                    lo=lo,
                    hi=hi,
                    caller=caller,
                    locale=ctx.locale,
                    limit=min(wanted - len(items), MAX_DATED_BATCH),
                )
            except DatedQueryError as exc:
                raise SourceError(_REASON_CODES.get(exc.reason, "field_changed")) from None
            items.extend(_item(hit, mapping, ctx) for hit in page.hits)
        return items

    async def _field_still_there(
        self, ctx: SourceContext, caller: DatedCaller | None, mapping: RecordDateMapping
    ) -> None:
        """A type the viewer may read whose mapped field was removed, retyped or unindexed is a
        named failure (``field_changed``), not a silent gap. The contract answers an empty page
        for a type that is unknown or not theirs and raises only for one that is: so anyone else
        learns nothing about which types or fields exist."""
        try:
            await dated_records(
                ctx.db,
                tenant_id=ctx.tenant_id,
                type_key=mapping.type_key,
                field=mapping.field,
                lo=date(2000, 1, 1),
                hi=date(2000, 1, 2),
                caller=caller,
                locale=ctx.locale,
                limit=1,
            )
        except DatedQueryError:
            raise SourceError("field_changed") from None
