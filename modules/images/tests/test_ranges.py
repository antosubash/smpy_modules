"""``sm_images.ranges``: one ``bytes=`` range, as the portal's ``range_response`` parsed it."""

from __future__ import annotations

import pytest
from sm_images.ranges import ByteRange, RangeNotSatisfiable, parse_range


@pytest.mark.parametrize(
    ("header", "want"),
    [
        (None, None),
        ("", None),
        ("items=0-1", None),
        ("bytes=0-1,4-5", None),  # several ranges: the whole object, as RFC 9110 allows
        ("bytes=x-1", None),
        ("bytes=5-2", None),
        ("bytes=", None),
        ("bytes=0-9", ByteRange(0, 9)),
        ("bytes=90-", ByteRange(90, 99)),
        ("bytes=90-500", ByteRange(90, 99)),
        ("bytes=-10", ByteRange(90, 99)),
        ("bytes=-500", ByteRange(0, 99)),
        (" bytes=1-2 ", ByteRange(1, 2)),
        ("bytes= 1 - 2", ByteRange(1, 2)),
    ],
)
def test_parse(header, want):
    assert parse_range(header, 100) == want


@pytest.mark.parametrize("header", ["bytes=100-", "bytes=200-300", "bytes=-0"])
def test_unsatisfiable(header):
    with pytest.raises(RangeNotSatisfiable):
        parse_range(header, 100)


def test_empty_object_is_unsatisfiable_for_any_range():
    with pytest.raises(RangeNotSatisfiable):
        parse_range("bytes=0-", 0)


def test_length():
    assert ByteRange(10, 19).length == 10


HUGE = "9" * 5000  # past Python's int-from-str digit limit: a ValueError if unbounded


@pytest.mark.parametrize(
    ("header", "want"),
    [
        (f"bytes=0-{HUGE}", ByteRange(0, 99)),  # a last-pos past the end is clamped
        (f"bytes=-{HUGE}", ByteRange(0, 99)),  # a suffix longer than the object: all of it
        (f"bytes={'0' * 30}5-{HUGE}", ByteRange(5, 99)),  # leading zeros are still small
    ],
    ids=["huge-last-pos", "huge-suffix", "zero-padded-first-pos"],
)
def test_huge_numbers_are_ranges_not_errors(header, want):
    assert parse_range(header, 100) == want


@pytest.mark.parametrize(
    "header", [f"bytes={HUGE}-", f"bytes={HUGE}-{HUGE}"], ids=["open", "closed"]
)
def test_a_huge_first_pos_is_unsatisfiable(header):
    with pytest.raises(RangeNotSatisfiable):
        parse_range(header, 100)
