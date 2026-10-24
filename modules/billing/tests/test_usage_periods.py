"""Which period a counter counts against (``metering.periods``)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_billing.constants import SubscriptionStatus
from sm_billing.metering.periods import as_utc, calendar_month, current_period
from sm_billing.models import Subscription

START = datetime(2026, 10, 7, 9, tzinfo=UTC)
END = datetime(2026, 11, 7, 9, tzinfo=UTC)
OCT = (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC))


def _sub(status=SubscriptionStatus.ACTIVE, start=START, end=END) -> Subscription:
    return Subscription(
        tenant_id="t1",
        plan_id=1,
        status=status,
        current_period_start=start,
        current_period_end=end,
    )


def test_inside_the_subscription_period():
    assert current_period(_sub(), datetime(2026, 10, 20, tzinfo=UTC)) == (START, END)


def test_start_is_inclusive_and_end_exclusive():
    assert current_period(_sub(), START) == (START, END)
    nov = (datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC))
    assert current_period(_sub(), END) == nov


def test_a_stale_period_falls_back_to_the_calendar_month():
    # A missed webhook left last period on the row.
    later = datetime(2026, 12, 3, tzinfo=UTC)
    assert current_period(_sub(), later) == calendar_month(later)


@pytest.mark.parametrize("status", [SubscriptionStatus.CANCELED, SubscriptionStatus.UNPAID])
def test_a_lapsed_subscription_uses_the_calendar_month(status):
    # Its tenant is on the default plan, which has no provider period.
    assert current_period(_sub(status), datetime(2026, 10, 20, tzinfo=UTC)) == OCT


def test_no_subscription_or_no_provider_period():
    now = datetime(2026, 10, 20, tzinfo=UTC)
    assert current_period(None, now) == OCT
    # The manual provider and pre-migration rows carry no start.
    assert current_period(_sub(start=None), now) == OCT


def test_trialing_and_past_due_keep_their_period():
    now = datetime(2026, 10, 20, tzinfo=UTC)
    for status in (SubscriptionStatus.TRIALING, SubscriptionStatus.PAST_DUE):
        assert current_period(_sub(status), now) == (START, END)


def test_december_rolls_into_the_next_year():
    assert calendar_month(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == (
        datetime(2026, 12, 1, tzinfo=UTC),
        datetime(2027, 1, 1, tzinfo=UTC),
    )


def test_naive_values_are_utc_as_sqlite_returns_them():
    naive_start, naive_end = START.replace(tzinfo=None), END.replace(tzinfo=None)
    sub = _sub(start=naive_start, end=naive_end)
    assert current_period(sub, datetime(2026, 10, 20, tzinfo=UTC)) == (START, END)
    assert as_utc(naive_start) == START
