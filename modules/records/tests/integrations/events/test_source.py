"""The ``records:dates`` source: what it puts on a calendar, for whom."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("sm_events")

from sm_events.calendar.plugin_validate import to_occurrences
from sm_events.contracts.extensions import SourceError
from sm_records.integrations.events.settings import (
    RecordDateMapping,
    RecordDatesSettings,
)
from sm_records.integrations.events.source import RecordDatesSource
from sm_records.models import RecordStatus

from tests.integrations.events.support import CALENDAR, add, context, make_type, viewer

START = datetime(2026, 7, 1, tzinfo=UTC)
END = datetime(2026, 8, 1, tzinfo=UTC)
SOURCE = RecordDatesSource()


def cfg(**kw):
    return RecordDatesSettings(
        mappings=[RecordDateMapping(type_key="deadlines", field="due", **kw)]
    )


async def read(db, settings=None, who="viewer", start=START, end=END, limit=500):
    ctx = context(db, settings or cfg(), viewer() if who == "viewer" else who, limit=limit)
    return list(await SOURCE.occurrences(ctx, start, end))


def test_the_source_is_registered_as_documented():
    assert SOURCE.id == "records:dates" and SOURCE.public is True
    assert SOURCE.settings_model is RecordDatesSettings
    assert SOURCE.label_key == "records.events.source.label"


async def test_date_field_all_day(db):
    rtype = await make_type(db)
    await add(db, rtype, "Tax", due="2026-07-15")
    (item,) = await read(db)
    assert item.all_day and (item.start_date.isoformat(), item.end_date.isoformat()) == (
        "2026-07-15",
        "2026-07-16",
    )
    assert item.start is None and item.end is None
    assert item.title == "Tax" and item.timezone == "Europe/Vienna"


async def test_date_field_with_end_field_spans_days(db):
    rtype = await make_type(db)
    await add(db, rtype, "Camp", due="2026-07-10", until="2026-07-12")
    (item,) = await read(db, cfg(end_field="until"))
    assert (item.start_date.isoformat(), item.end_date.isoformat()) == ("2026-07-10", "2026-07-13")


async def test_datetime_with_end_field(db):
    rtype = await make_type(db)
    await add(db, rtype, "Talk", at="2026-07-05T10:00:00+00:00", ends="2026-07-05T12:30:00+00:00")
    settings = RecordDatesSettings(
        mappings=[RecordDateMapping(type_key="deadlines", field="at", end_field="ends")]
    )
    (item,) = await read(db, settings)
    assert not item.all_day
    assert (item.start, item.end) == (
        datetime(2026, 7, 5, 10, tzinfo=UTC),
        datetime(2026, 7, 5, 12, 30, tzinfo=UTC),
    )


async def test_datetime_duration_fallback_and_end_before_start(db):
    rtype = await make_type(db)
    await add(db, rtype, "No end", at="2026-07-05T10:00:00+00:00")
    await add(
        db, rtype, "Backwards", at="2026-07-06T10:00:00+00:00", ends="2026-07-06T09:00:00+00:00"
    )
    settings = RecordDatesSettings(
        mappings=[
            RecordDateMapping(
                type_key="deadlines", field="at", end_field="ends", duration_minutes=90
            )
        ]
    )
    items = {i.title: i for i in await read(db, settings)}
    for title in ("No end", "Backwards"):
        assert (items[title].end - items[title].start).total_seconds() == 90 * 60


async def test_lookback_shows_running_multi_day(db):
    rtype = await make_type(db)
    await add(db, rtype, "Started in June", due="2026-06-25", until="2026-07-03")
    await add(db, rtype, "Long ago", due="2026-04-01", until="2026-04-02")
    items = await read(db, cfg(end_field="until"))
    assert [i.title for i in items] == ["Started in June"]  # to_occurrences keeps what intersects
    kept = to_occurrences(
        items, source_id="records:dates", calendar=CALENDAR, start=START, end=END, default_lang="en"
    )
    assert [o.title for o in kept] == ["Started in June"]


async def test_key_title_url_shape(db):
    rtype = await make_type(db)
    record = await add(db, rtype, "A <b>title</b>", due="2026-07-15")
    (item,) = await read(db)
    assert item.key == f"deadlines:{record.uuid}:due"
    assert item.url == f"/admin/records/deadlines/{record.uuid}"
    assert item.title == "A <b>title</b>"  # text: the events side escapes it everywhere
    assert item.color is None
    colored = await read(db, cfg(color="#aa0000"))
    assert colored[0].color == "#aa0000"


async def test_a_record_without_a_title_gets_the_type_key(db):
    rtype = await make_type(db)
    await add(db, rtype, "", due="2026-07-15")
    (item,) = await read(db)
    assert item.title  # never empty: an empty title would refuse the whole answer


async def test_anonymous_url_none_and_public_types_only(db):
    private = await make_type(db, "deadlines")
    public = await make_type(db, "open_dates", is_public=True)
    await add(db, private, "secret", due="2026-07-15")
    record = await add(db, public, "open", due="2026-07-15")
    both = RecordDatesSettings(
        mappings=[
            RecordDateMapping(type_key="deadlines", field="due"),
            RecordDateMapping(type_key="open_dates", field="due"),
        ]
    )
    items = await read(db, both, who=None)
    assert [(i.title, i.url) for i in items] == [("open", None)]
    assert items[0].key == f"open_dates:{record.uuid}:due"


async def test_drafts_are_never_shown(db):
    rtype = await make_type(db)
    await add(db, rtype, "draft", due="2026-07-15", status=RecordStatus.DRAFT)
    assert await read(db) == []
    assert await read(db, who=None) == []


async def test_role_narrowed_type_hidden_for_viewer(db):
    rtype = await make_type(db, allowed_roles=["editor"])
    await add(db, rtype, "r", due="2026-07-15")
    assert await read(db, who=viewer("viewer")) == []
    assert len(await read(db, who=viewer("editor"))) == 1
    assert await read(db, who=viewer(perms=())) == []


async def test_limit_plus_one(db):
    rtype = await make_type(db)
    for i in range(6):
        await add(db, rtype, f"r{i}", due=f"2026-07-{i + 1:02d}")
    items = await read(db, limit=3)
    assert len(items) == 4  # limit + 1: the runner marks the call over its limit truncated


async def test_a_field_changed_since_is_a_named_failure(db):
    await make_type(db)
    settings = RecordDatesSettings(
        mappings=[RecordDateMapping(type_key="deadlines", field="title")]
    )
    with pytest.raises(SourceError) as caught:
        await read(db, settings)
    assert caught.value.code == "field_changed"


async def test_a_type_that_is_gone_shows_nothing(db):
    assert (
        await read(
            db, RecordDatesSettings(mappings=[RecordDateMapping(type_key="nope", field="due")])
        )
        == []
    )


async def test_items_validate_through_events(db):
    rtype = await make_type(db)
    await add(db, rtype, "Tax", due="2026-07-15")
    await add(db, rtype, "Talk", at="2026-07-05T10:00:00+00:00")
    settings = RecordDatesSettings(
        mappings=[
            RecordDateMapping(type_key="deadlines", field="due"),
            RecordDateMapping(type_key="deadlines", field="at"),
        ]
    )
    items = await read(db, settings)
    kept = to_occurrences(
        items, source_id="records:dates", calendar=CALENDAR, start=START, end=END, default_lang="en"
    )
    assert sorted(o.title for o in kept) == ["Talk", "Tax"]


async def test_a_date_field_that_is_no_longer_indexed_is_a_named_failure(db):
    """The type has no indexed date field left at all, so it drops out of the type list: still a
    named failure for someone who may read the type, not a silent gap."""
    from sm_records.records.services import types as type_service

    from tests.integrations.events.support import SETTINGS, field

    await type_service.create_type(
        db,
        key="deadlines",
        label="Deadlines",
        fields_raw=[field("title", "text", indexed=False), field("due", "date", indexed=False)],
        settings=SETTINGS,
    )
    with pytest.raises(SourceError) as caught:
        await read(db)
    assert caught.value.code == "field_changed"
    assert await read(db, who=viewer(perms=())) == []  # someone who may not read it learns nothing
