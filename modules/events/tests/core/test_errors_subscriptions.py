"""The refusals of external subscriptions (PR 10): status, code and the closed body."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sm_events.core import constants
from sm_events.core import errors_subscriptions as sub
from sm_events.core.errors import EventsError, install_exception_handlers

CASES = [
    (sub.SubscriptionExists, 409, "subscription_exists"),
    (sub.SubscriptionLimit, 409, "subscription_limit"),
    (sub.SubscriptionNotPublicCalendar, 422, "subscription_not_public_calendar"),
]


async def _get(exc: Exception):
    app = FastAPI()
    install_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise exc

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
        return await http.get("/boom")


@pytest.mark.parametrize(("cls", "status", "code"), CASES)
async def test_subscription_codes(cls, status, code):
    got = await _get(cls())
    assert got.status_code == status
    assert set(got.json()) == {"detail", "code"}
    assert got.json()["code"] == code
    assert got.json()["detail"]


@pytest.mark.parametrize("code", sorted(set(constants.URL_REFUSAL_CODES.values())))
async def test_url_refused_carries_one_of_the_closed_codes(code):
    got = await _get(sub.UrlRefused(code))
    assert got.status_code == 422
    assert got.json()["code"] == code
    assert got.json()["detail"] == constants.URL_REFUSAL_DETAIL[code]


def test_url_refused_refuses_an_unknown_code():
    with pytest.raises(ValueError, match="closed set"):
        sub.UrlRefused("anything_else")


async def test_refresh_too_soon_sends_retry_after():
    got = await _get(sub.RefreshTooSoon(retry_after=120))
    assert got.status_code == 429
    assert got.headers["retry-after"] == "120"
    assert got.json()["code"] == "refresh_too_soon"
    assert set(got.json()) == {"detail", "code"}


def test_all_are_events_errors():
    for cls in (sub.SubscriptionExists, sub.UrlRefused, sub.RefreshTooSoon):
        assert issubclass(cls, EventsError)


def test_a_guard_refusal_and_a_missing_host_look_the_same_to_a_user():
    """Oracle guard: no code tells an internal address from a host that does not resolve."""
    refusals = constants.URL_REFUSAL_CODES
    assert refusals["non_public_address"] == refusals["unresolvable_host"]


def test_failure_codes_are_a_closed_set_that_covers_every_refusal():
    failures = set(constants.SUBSCRIPTION_FAILURE_CODES)
    assert set(constants.URL_REFUSAL_CODES.values()) <= failures
    assert {
        "timeout",
        "connect_failed",
        "tls_failed",
        "http_status",
        "gone",
        "too_large",
    } <= failures
    assert len(failures) == len(constants.SUBSCRIPTION_FAILURE_CODES)
    assert all(len(code) <= constants.SUBSCRIPTION_CODE_MAX for code in failures)
