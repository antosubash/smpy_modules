"""Whatever goes wrong inside the connection layer, what leaves ``fetch_feed`` is a code."""

from __future__ import annotations

import json
import traceback

import httpx
import pytest
from sm_events.feeds.subscriptions.errors import FetchFailure

from tests.support.net import PUBLIC_IP, failure_code, fetch, inner, resolver  # noqa: F401

ADDRESS = "https://cal.example/private/ADDRESS-TOKEN-123/basic.ics?key=SECRET2"
ERRORS = [
    RuntimeError,
    ValueError,
    KeyError,
    OSError,
    TypeError,
    UnicodeError,
    json.JSONDecodeError,
    httpx.InvalidURL,
    httpx.DecodingError,
    httpx.TooManyRedirects,
    AssertionError,
    ZeroDivisionError,
]


def _make(kind, text):
    return kind(text, "", 0) if kind is json.JSONDecodeError else kind(text)


@pytest.fixture(autouse=True)
def _host(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP]


def _clean(failure: BaseException) -> None:
    blob = (
        str(failure)
        + repr(failure)
        + repr(failure.args)
        + "".join(traceback.format_exception(failure))
    )
    assert "SECRET-TOKEN" not in blob and "SECRET2" not in blob
    assert failure.__cause__ is None and failure.__context__ is None


@pytest.mark.parametrize("kind", ERRORS)
async def test_an_unexpected_exception_in_the_connection_layer_carries_no_url(inner, kind):  # noqa: F811
    def boom(request):
        raise _make(kind, f"failed for {request.url}")

    inner(boom)
    with pytest.raises(FetchFailure) as caught:
        await fetch(ADDRESS)
    assert caught.value.code in {"connect_failed", "url_invalid", "timeout"}
    _clean(caught.value)


@pytest.mark.parametrize("kind", ERRORS)
async def test_an_unexpected_exception_while_reading_the_body_carries_no_url(inner, kind):  # noqa: F811
    async def body():
        yield b"BEGIN:VCALENDAR\r\n"
        raise _make(kind, f"read failed for {ADDRESS}")

    inner(lambda r: httpx.Response(200, headers={"content-type": "text/calendar"}, content=body()))
    with pytest.raises(FetchFailure) as caught:
        await fetch(ADDRESS)
    _clean(caught.value)


async def test_every_failure_that_leaves_has_a_clean_chain(inner):  # noqa: F811
    inner(lambda r: httpx.Response(500))
    with pytest.raises(FetchFailure) as caught:
        await fetch(ADDRESS)
    _clean(caught.value)
    assert await failure_code(ADDRESS.replace("https", "ftp")) == "url_scheme"
