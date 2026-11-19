"""The address never reaches a log record, an exception text or a traceback."""

from __future__ import annotations

import logging
import traceback

import httpx
import pytest
from sm_events.feeds.subscriptions.errors import FetchFailure

from tests.support.net import (  # noqa: F401 - fixtures
    OTHER_PUBLIC_IP,
    PUBLIC_IP,
    fetch,
    ics,
    inner,
    resolver,
)


@pytest.fixture(autouse=True)
def _hosts(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP]
    resolver["b.example"] = [OTHER_PUBLIC_IP]
    resolver["internal.example"] = ["10.0.0.1"]


def _redirect(location: str) -> httpx.Response:
    return httpx.Response(302, headers={"location": location})


SECRET_URL = "https://cal.example/private-TOKEN123/basic.ics?key=TOKEN123"


def _no_token(text: str) -> None:
    assert "TOKEN123" not in text


@pytest.mark.parametrize("scenario", ["ok", "redirect", "refused_redirect", "500", "boom"])
async def test_no_url_in_any_log_record(inner, caplog, scenario):  # noqa: F811
    def handler(request):
        if scenario == "redirect" and request.url.host == PUBLIC_IP:
            return _redirect("https://b.example/private-TOKEN123/x.ics")
        if scenario == "refused_redirect":
            return _redirect("https://internal.example/private-TOKEN123/x.ics")
        if scenario == "500":
            return httpx.Response(500)
        if scenario == "boom":  # a library that quotes the URL in its message
            raise httpx.ConnectError(f"cannot connect to {request.url} {SECRET_URL}")
        return ics()

    inner(handler)
    with caplog.at_level(logging.DEBUG):
        try:
            await fetch(SECRET_URL)
        except FetchFailure as failure:
            _no_token(str(failure) + repr(failure) + repr(failure.args))
            _no_token("".join(traceback.format_exception(failure)))
    for record in caplog.records:
        _no_token(record.getMessage() + repr(record.__dict__))
        if record.exc_text:
            _no_token(record.exc_text)


async def test_a_failure_drops_the_exception_that_caused_it(inner):  # noqa: F811
    def handler(request):
        raise httpx.ConnectError(f"cannot connect to {SECRET_URL}", request=request)

    inner(handler)
    with pytest.raises(FetchFailure) as caught:
        await fetch(SECRET_URL)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    assert caught.value.code == "connect_failed"


async def test_an_unknown_failure_code_is_refused():
    with pytest.raises(ValueError, match="closed set"):
        FetchFailure("the remote said: nope")
