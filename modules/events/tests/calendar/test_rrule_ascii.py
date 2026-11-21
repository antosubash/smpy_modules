# ruff: noqa: RUF001 - the inputs are the point: look-alike digits and spaces
"""The RRULE parser accepts ASCII only: no Unicode digits, no stripped whitespace."""

from __future__ import annotations

import pytest
from sm_events.calendar import rrule
from sm_events.core.errors import InvalidRule


@pytest.mark.parametrize(
    "text",
    [
        "FREQ=DAILY;COUNT=٣",  # ARABIC-INDIC DIGIT THREE
        "FREQ=DAILY;INTERVAL=２",  # FULLWIDTH DIGIT TWO
        "FREQ=WEEKLY;BYDAY=MO ",
        "FREQ=WEEKLY;BYDAY=MO ",  # NBSP
        "FREQ=WEEKLY;BYDAY= MO",
        "FREQ=WEEKLY; BYDAY=MO",
        "FREQ=MONTHLY;BYDAY=٢MO",
        " FREQ=DAILY",
        "FREQ=DAILY ",
        "FREQ=DAILY;COUNT=3\n",
    ],
)
def test_non_ascii_or_padded_rules_are_refused(text):
    with pytest.raises(InvalidRule) as caught:
        rrule.parse(text, all_day=False, timezone="UTC")
    assert caught.value.code == "invalid_rrule"


def test_plain_ascii_still_parses():
    assert rrule.parse("rrule:freq=weekly;byday=mo", all_day=False, timezone="UTC").text == (
        "FREQ=WEEKLY;BYDAY=MO"
    )
