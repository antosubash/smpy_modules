"""EXDATE values read one by one, and local or floating UNTIL values."""

from __future__ import annotations

from tests.feeds.importing.mapping import event, one
from tests.feeds.importing.test_mapper_series import VIENNA, series, utc


def test_one_bad_exdate_does_not_drop_the_others():
    item = one(
        *series(
            f"EXDATE;{VIENNA}:20260713T100000",
            "EXDATE;TZID=Nowhere/Zone:20260720T100000",
            "EXDATE;TZID=Europe/Vienna:garbage",
            count=5,
        )
    )
    assert [(o.original_start, o.kind) for o in item.event.overrides] == [(utc(13), "skipped")]  # type: ignore[union-attr]
    assert "exdate_ignored" in item.notes


def test_one_bad_value_in_a_list_does_not_drop_the_good_ones():
    item = one(*series(f"EXDATE;{VIENNA}:20260713T100000,garbage,20260727T100000", count=5))
    assert [o.original_start for o in item.event.overrides] == [utc(13), utc(27)]  # type: ignore[union-attr]
    assert "exdate_ignored" in item.notes


def test_a_date_valued_exdate_on_a_timed_series_skips_that_days_occurrence():
    item = one(*series("EXDATE;VALUE=DATE:20260713,20260727", count=5))
    assert [(o.original_start, o.kind) for o in item.event.overrides] == [  # type: ignore[union-attr]
        (utc(13), "skipped"),
        (utc(27), "skipped"),
    ]
    assert "exdate_ignored" not in item.notes
    stray = one(*series("EXDATE;VALUE=DATE:20260714", count=5))  # a Tuesday: no occurrence
    assert stray.event.overrides == [] and "exdate_ignored" in stray.notes  # type: ignore[union-attr]


def test_a_floating_series_with_a_floating_until_imports():
    lines = event(
        "f@x",
        "RRULE:FREQ=WEEKLY;UNTIL=20260727T235959",
        start="20260706T100000",
        end="20260706T110000",
    )
    item = one(*lines)
    assert item.skip is None and "floating_time" in item.notes
    assert item.event.rrule == "FREQ=WEEKLY;UNTIL=20260727T215959Z"  # type: ignore[union-attr]  # Vienna to UTC


def test_a_tzid_series_with_a_local_until_imports_too():
    lines = series("RRULE:FREQ=WEEKLY;UNTIL=20260727T000000")
    lines = [line for line in lines if line != "RRULE:FREQ=WEEKLY;COUNT=8"]
    item = one(*lines)
    assert item.skip is None and item.event.rrule.endswith("UNTIL=20260726T220000Z")  # type: ignore[union-attr]
