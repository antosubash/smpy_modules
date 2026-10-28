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
