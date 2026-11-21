"""When a subscription is fetched next: interval, jitter, backoff, politeness and disabling."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest
from sm_events.core import constants
from sm_events.feeds.subscriptions import schedule

NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)


def rng() -> random.Random:
    return random.Random(7)


def test_clamp():
    assert schedule.effective_minutes(5, 60) == 15
    assert schedule.effective_minutes(2000, 60) == 1440
    assert schedule.effective_minutes(None, 60) == 60
    assert schedule.effective_minutes(None, 1) == 15
    assert schedule.effective_minutes(None, 10**9) == 1440
    assert schedule.effective_minutes(30, 60) == 30


def test_jitter_bounds():
    r = rng()
    for _ in range(1000):
        delay = schedule.after_success(NOW, 60, r) - NOW
        assert timedelta(minutes=54) <= delay <= timedelta(minutes=66)


def test_a_server_that_says_how_long_to_cache_is_believed_up_to_a_ceiling():
    day = timedelta(days=1)
    slow = schedule.after_success(NOW, 60, rng(), max_age=6 * 3600) - NOW
    assert timedelta(hours=5.3) <= slow <= timedelta(hours=6.7)  # longer than our interval
    assert schedule.after_success(NOW, 60, rng(), max_age=60) - NOW >= timedelta(minutes=54)
    assert schedule.after_success(NOW, 60, rng(), max_age=10**9) - NOW <= day * 1.1  # the ceiling
    assert schedule.after_success(NOW, 60, rng(), max_age=0) - NOW >= timedelta(minutes=54)


@pytest.mark.parametrize(
    ("failures", "hours"), [(1, 1), (2, 2), (3, 4), (4, 8), (5, 16), (6, 24), (9, 24)]
)
def test_backoff_doubles_and_caps(failures, hours):
    at, status = schedule.after_failure(NOW, 60, failures, "timeout", rng())
    assert status == "error"
    delay = at - NOW
    assert timedelta(hours=hours * 0.9) <= delay <= timedelta(hours=hours * 1.1)


def test_a_retry_after_is_honoured_up_to_the_ceiling():
    at, _ = schedule.after_failure(NOW, 15, 1, "http_status", rng(), retry_after=3 * 3600)
    assert at - NOW >= timedelta(hours=3)
    at, _ = schedule.after_failure(NOW, 15, 1, "http_status", rng(), retry_after=10**9)
    assert at - NOW <= constants.SUBSCRIPTION_MAX_BACKOFF * 1.1
    at, _ = schedule.after_failure(NOW, 15, 3, "http_status", rng(), retry_after=60)
    assert at - NOW >= timedelta(minutes=15 * 4 * 0.9)  # the backoff still wins when longer


def test_disable_after_ten():
    assert schedule.after_failure(NOW, 60, 9, "timeout", rng())[1] == "error"
    assert schedule.after_failure(NOW, 60, 10, "timeout", rng())[1] == "disabled"
    assert schedule.after_failure(NOW, 60, 11, "timeout", rng())[1] == "disabled"


@pytest.mark.parametrize("code", ["gone", "url_unreadable"])
def test_gone_and_unreadable_disable_at_once(code):
    assert schedule.after_failure(NOW, 60, 1, code, rng())[1] == "disabled"


@pytest.mark.parametrize("code", ["url_unreachable", "url_scheme", "url_port", "insecure_redirect"])
def test_url_codes_do_not_disable_at_once(code):
    assert schedule.after_failure(NOW, 60, 1, code, rng())[1] == "error"
