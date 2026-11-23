"""A mapped event as the columns the read needs: UTC, the rule, and the prefilter span."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sm_events.core import constants
from sm_events.feeds.importing.values import ItemSkip
from sm_events.feeds.subscriptions import items

from tests.feeds.importing.mapping import event, mapped
from tests.support.subscriptions import vevent


def _values(*lines: str, **kw):
    got = mapped(*lines, **kw)
    return [items.to_values(i.event) for i in got.items if i.event is not None]


def _one(*lines: str, **kw):
    (value,) = _values(*lines, **kw)
    return value


def test_one_off_columns():
    v = _one(*vevent())
    assert v.starts_at == datetime(2026, 7, 1, 10, tzinfo=UTC)
    assert v.ends_at == datetime(2026, 7, 1, 11, tzinfo=UTC)
    assert (v.span_start, v.span_end) == (v.starts_at, v.ends_at)
    assert v.rrule is None and v.recurrence_until is None and v.overrides == []
    assert (v.title, v.cancelled, v.private_class) == ("Talk", False, False)


def test_series_span_with_count_and_endless_and_moves():
    weekly = vevent(RRULE="FREQ=WEEKLY;COUNT=3")
    v = _one(*weekly)
    assert v.recurrence_until == datetime(2026, 7, 15, 11, tzinfo=UTC)
    assert v.span_end == v.recurrence_until
    assert _one(*vevent(RRULE="FREQ=WEEKLY")).span_end is None
    later = vevent(
        **{"RECURRENCE-ID": "20260708T100000Z", "DTSTART": "20260729T100000Z"},
        DTEND="20260729T110000Z",
    )
    moved = _one(*weekly, *later)
    assert moved.span_end == datetime(2026, 7, 29, 11, tzinfo=UTC)
    assert [o["kind"] for o in moved.overrides] == ["moved"]
    assert moved.overrides[0]["starts_at"] == "2026-07-29T10:00:00+00:00"
    earlier = vevent(
        **{"RECURRENCE-ID": "20260708T100000Z", "DTSTART": "20260625T100000Z"},
        DTEND="20260625T110000Z",
    )
    assert _one(*weekly, *earlier).span_start == datetime(2026, 6, 25, 10, tzinfo=UTC)


def test_all_day_uses_pr2_convention():
    v = _one(*vevent(**{"DTSTART;VALUE=DATE": "20260701", "DTEND;VALUE=DATE": "20260702"}))
    assert v.all_day is True
    assert v.starts_at == datetime(2026, 6, 30, 22, tzinfo=UTC)  # Vienna midnight
    assert v.ends_at == datetime(2026, 7, 1, 22, tzinfo=UTC)  # exclusive


def test_hash_stable_and_sensitive():
    a = _one(*vevent())
    assert a.content_hash == _one(*vevent()).content_hash
    assert len(a.content_hash) == 64
    changes = [
        {"title": "Other"},
        {"location": "Room"},
        {"url": "https://x.example/"},
        {"cancelled": True},
        {"private_class": True},
        {"all_day": True},
        {"timezone": "UTC"},
        {"rrule": "FREQ=DAILY"},
    ]
    for change in changes:
        assert items.hash_of(replace(a, **change)) != a.content_hash, change


def test_title_html_is_text():
    v = _one(*event("a@x", summary="<img src=x onerror=alert(1)>\x07"))
    assert v.title == "<img src=x onerror=alert(1)>"


def test_title_and_location_and_url_are_bounded():
    v = _one(*vevent(SUMMARY="t" * 400, LOCATION="l" * 300, URL="https://a.example/x"))
    assert len(v.title) == 300 and len(v.location) == 200
    assert v.url == "https://a.example/x"


def test_attendees_and_organisers_are_not_values():
    v = _one(*vevent("ATTENDEE;CN=A:mailto:a@example.com", "ORGANIZER:mailto:o@example.com"))
    blob = repr(v)
    assert "example.com" not in blob and "mailto" not in blob


def test_a_time_or_rule_the_module_refuses_skips_the_item():
    mapped_event = mapped(*vevent()).items[0].event
    bad_times = mapped_event.model_copy(
        update={"times": mapped_event.times.model_copy(update={"end": "2026-07-01T09:00"})}
    )
    with pytest.raises(ItemSkip):
        items.to_values(bad_times)
    with pytest.raises(ItemSkip):
        items.to_values(mapped_event.model_copy(update={"rrule": "FREQ=SECONDLY"}))


@pytest.mark.parametrize("klass", ["PRIVATE", "CONFIDENTIAL"])
def test_a_private_event_is_kept_as_busy_with_its_time_only(klass):
    v = _one(
        *vevent(
            SUMMARY="Salary talk",
            LOCATION="Room Secret",
            URL="https://x.example/secret",
            CLASS=klass,
        )
    )
    assert v.private_class is True
    assert (v.title, v.location, v.url) == (constants.SUBSCRIPTION_BUSY_TITLE, None, None)
    assert v.starts_at == datetime(2026, 7, 1, 10, tzinfo=UTC)  # the time stays
    assert "Salary" not in repr(v) and "Secret" not in repr(v)


def test_a_public_event_keeps_its_text():
    v = _one(*vevent(SUMMARY="Talk", LOCATION="Room", CLASS="PUBLIC"))
    assert (v.private_class, v.title, v.location) == (False, "Talk", "Room")
