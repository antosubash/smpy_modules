"""What a server says about when to come back: ``Cache-Control: max-age`` and ``Retry-After``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from sm_events.feeds.subscriptions.errors import FetchFailure

from tests.support.net import PUBLIC_IP, fetch, ics, inner, resolver  # noqa: F401

URL = "https://cal.example/feed.ics"


@pytest.fixture(autouse=True)
def _host(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP]


@pytest.mark.parametrize(
    ("header", "seconds"),
    [
        ("max-age=3600", 3600),
        ("public, max-age=600, must-revalidate", 600),
        ("MAX-AGE=60", 60),
        ("no-cache", None),
        ("max-age=abc", None),
        ("max-age=-5", None),
        ("max-age=0", None),
        ("", None),
    ],
)
async def test_max_age_is_read(inner, header, seconds):  # noqa: F811
    inner(lambda r: ics(**({"cache-control": header} if header else {})))
    assert (await fetch(URL)).max_age == seconds


async def test_a_304_carries_max_age_too(inner):  # noqa: F811
    inner(lambda r: httpx.Response(304, headers={"cache-control": "max-age=900"}))
    assert (await fetch(URL, etag='"v1"')).max_age == 900


@pytest.mark.parametrize("status", [429, 503, 500])
async def test_retry_after_seconds(inner, status):  # noqa: F811
    inner(lambda r: httpx.Response(status, headers={"retry-after": "120"}))
    with pytest.raises(FetchFailure) as caught:
        await fetch(URL)
    assert caught.value.retry_after == 120


async def test_retry_after_date(inner):  # noqa: F811
    when = datetime.now(UTC) + timedelta(hours=2)
    inner(
        lambda r: httpx.Response(503, headers={"retry-after": format_datetime(when, usegmt=True)})
    )
    with pytest.raises(FetchFailure) as caught:
        await fetch(URL)
    assert 7000 <= caught.value.retry_after <= 7300


@pytest.mark.parametrize("value", ["soon", "-5", "", "99999999999999999999"])
async def test_a_bad_retry_after_is_ignored(inner, value):  # noqa: F811
    inner(lambda r: httpx.Response(503, headers={"retry-after": value}))
    with pytest.raises(FetchFailure) as caught:
        await fetch(URL)
    assert caught.value.retry_after is None or caught.value.retry_after > 0
    assert caught.value.code == "http_status"
