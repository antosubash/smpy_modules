"""One fetch: headers, conditional requests, redirects checked hop by hop, and what a failure
may say. Fake DNS and a fake connection layer only: nothing here touches the network."""

from __future__ import annotations

import re

import httpx
import pytest
from sm_events.feeds.subscriptions import fetch as fetch_module
from sm_events.feeds.subscriptions.errors import FetchFailure

from tests.support.net import (  # noqa: F401 - fixtures
    ICS,
    OTHER_PUBLIC_IP,
    PUBLIC_IP,
    failure_code,
    fetch,
    ics,
    inner,
    resolver,
)

URL = "https://cal.example/feed.ics"


@pytest.fixture(autouse=True)
def _hosts(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP]
    resolver["b.example"] = [OTHER_PUBLIC_IP]
    resolver["internal.example"] = ["10.0.0.1"]


def _redirect(location: str | None, status: int = 302) -> httpx.Response:
    headers = {"location": location} if location is not None else {}
    return httpx.Response(status, headers=headers)


async def test_ok_returns_body_and_validators(inner):  # noqa: F811
    seen = inner(lambda r: ics(etag='"v1"', **{"last-modified": "Wed, 01 Jul 2026 10:00:00 GMT"}))
    result = await fetch(URL)
    assert result.status == "ok"
    assert result.body == ICS
    assert result.http_status == 200
    assert result.etag == '"v1"'
    assert result.last_modified == "Wed, 01 Jul 2026 10:00:00 GMT"
    assert len(seen) == 1


async def test_headers_exact(inner):  # noqa: F811
    seen = inner(lambda r: ics())
    await fetch(URL)
    headers = seen[0].headers
    assert set(headers.keys()) == {"host", "user-agent", "accept", "accept-encoding"}
    assert headers["host"] == "cal.example"
    assert headers["accept-encoding"] == "identity"
    assert headers["accept"] == "text/calendar, text/plain;q=0.5"
    assert re.fullmatch(r"SimpleModule-Events/\S+", headers["user-agent"])
    assert headers["user-agent"] == fetch_module.USER_AGENT
    for forbidden in ("cookie", "authorization", "referer", "proxy-authorization", "origin"):
        assert forbidden not in headers
    assert seen[0].method == "GET"
    assert seen[0].url.path == "/feed.ics"


async def test_the_user_agent_names_no_site_tenant_or_person():
    ua = fetch_module.USER_AGENT
    assert ua.startswith("SimpleModule-Events/")
    assert "@" not in ua and "http" not in ua and "(" not in ua


async def test_conditional_headers_are_sent(inner):  # noqa: F811
    seen = inner(lambda r: ics())
    await fetch(URL, etag='"v1"', last_modified="Wed, 01 Jul 2026 10:00:00 GMT")
    assert seen[0].headers["if-none-match"] == '"v1"'
    assert seen[0].headers["if-modified-since"] == "Wed, 01 Jul 2026 10:00:00 GMT"


async def test_conditional_headers_first_hop_only(inner):  # noqa: F811
    def handler(request):
        if request.url.host == PUBLIC_IP:
            return _redirect("https://b.example/feed.ics")
        return ics()

    seen = inner(handler)
    await fetch(URL, etag='"v1"', last_modified="x")
    assert "if-none-match" in seen[0].headers
    assert "if-none-match" not in seen[1].headers
    assert "if-modified-since" not in seen[1].headers


async def test_validators_that_are_not_printable_ascii_are_never_sent(inner):  # noqa: F811
    seen = inner(lambda r: ics())
    await fetch(URL, etag="bad\tvalue\x7f", last_modified="é" * 3)
    assert "if-none-match" not in seen[0].headers
    assert "if-modified-since" not in seen[0].headers


async def test_304_is_not_modified(inner):  # noqa: F811
    inner(lambda r: httpx.Response(304))
    result = await fetch(URL, etag='"v1"')
    assert (result.status, result.body, result.http_status) == ("not_modified", b"", 304)


async def test_304_nobody_asked_for_is_a_status_failure(inner):  # noqa: F811
    inner(lambda r: httpx.Response(304))
    assert await failure_code(URL) == "http_status"


async def test_410_is_gone(inner):  # noqa: F811
    inner(lambda r: httpx.Response(410))
    with pytest.raises(FetchFailure) as caught:
        await fetch(URL)
    assert (caught.value.code, caught.value.http_status) == ("gone", 410)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502, 503])
async def test_status_codes(inner, status):  # noqa: F811
    inner(lambda r: httpx.Response(status, content=b"<html>secret page</html>"))
    with pytest.raises(FetchFailure) as caught:
        await fetch(URL)
    assert (caught.value.code, caught.value.http_status) == ("http_status", status)
    assert "secret" not in str(caught.value) + repr(caught.value)  # no body, no reason text


async def test_redirect_followed_and_each_hop_pinned(inner):  # noqa: F811
    def handler(request):
        if request.url.host == PUBLIC_IP:
            return _redirect("https://b.example/other.ics", 301)
        return ics()

    seen = inner(handler)
    result = await fetch(URL)
    assert result.status == "ok"
    assert [(r.url.host, r.headers["host"]) for r in seen] == [
        (PUBLIC_IP, "cal.example"),
        (OTHER_PUBLIC_IP, "b.example"),
    ]
    assert seen[1].url.path == "/other.ics"


async def test_relative_redirect_is_joined(inner):  # noqa: F811
    def handler(request):
        return _redirect("/moved.ics") if request.url.path == "/feed.ics" else ics()

    seen = inner(handler)
    await fetch(URL)
    assert [r.url.path for r in seen] == ["/feed.ics", "/moved.ics"]
    assert {r.headers["host"] for r in seen} == {"cal.example"}


async def test_a_webcal_redirect_target_is_followed_as_https(inner):  # noqa: F811
    def handler(request):
        return _redirect("webcal://b.example/x.ics") if request.url.host == PUBLIC_IP else ics()

    seen = inner(handler)
    assert (await fetch(URL)).status == "ok"
    assert seen[1].headers["host"] == "b.example"


@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/latest/meta-data/",
        "https://169.254.169.254/latest/meta-data/",
        "https://internal.example/",
        "webcal://internal.example/",
        "https://[::ffff:7f00:1]/",
        "https://127.0.0.1/",
        "https://2130706433/",
        "https://u:p@b.example/",
        "https://b.example:8443/",
    ],
)
async def test_redirect_to_private_refused(inner, location):  # noqa: F811
    def handler(request):
        return _redirect(location)

    seen = inner(handler)
    code = await failure_code(URL)
    assert code.startswith("url_"), code
    assert [r.headers["host"] for r in seen] == ["cal.example"]  # the second host was never dialled


async def test_a_redirect_to_an_internal_name_and_to_a_missing_one_look_the_same(inner):  # noqa: F811
    codes = []
    for target in ("https://internal.example/", "https://nowhere.example/"):
        inner(lambda r, target=target: _redirect(target))
        codes.append(await failure_code(URL))
    assert codes == ["url_unreachable", "url_unreachable"]


async def test_https_to_http_refused(inner):  # noqa: F811
    seen = inner(lambda r: _redirect("http://b.example/feed.ics"))
    assert await failure_code(URL, intranet=True) == "insecure_redirect"  # even with the switch
    assert await failure_code(URL) == "url_scheme"  # without it the scheme is refused outright
    assert {r.headers["host"] for r in seen} == {"cal.example"}


async def test_http_to_https_and_http_to_http_are_fine_on_an_intranet(inner):  # noqa: F811
    def handler(request):
        return _redirect("http://b.example/feed.ics") if request.url.host == PUBLIC_IP else ics()

    inner(handler)
    assert (await fetch("http://cal.example/feed.ics", intranet=True)).status == "ok"


async def test_redirect_loop_capped(inner):  # noqa: F811
    def handler(request):
        other = "https://b.example/feed.ics" if request.url.host == PUBLIC_IP else URL
        return _redirect(other)

    seen = inner(handler)
    assert await failure_code(URL) == "too_many_redirects"
    assert len(seen) == 4  # the first request and three followed hops


async def test_redirect_without_location(inner):  # noqa: F811
    inner(lambda r: _redirect(None, 302))
    with pytest.raises(FetchFailure) as caught:
        await fetch(URL)
    assert (caught.value.code, caught.value.http_status) == ("http_status", 302)


async def test_an_unusable_location_is_invalid(inner):  # noqa: F811
    for location in ("javascript:alert(1)", "https://x.example:abc/", "https://exa\u2044mple.com/"):
        inner(lambda r, location=location: _redirect(location))
        assert (await failure_code(URL)).startswith("url_")


async def test_rebinding_between_save_and_fetch(inner, resolver):  # noqa: F811
    from sm_events.feeds.subscriptions import policy

    policy.resolve_allowed(httpx.URL(URL), policy.Policy())  # the save-time check passes
    resolver["cal.example"] = ["10.0.0.1"]  # then DNS changes
    seen = inner(lambda r: ics())
    assert await failure_code(URL) == "url_unreachable"
    assert seen == []  # nothing was dialled


async def test_the_save_time_answer_does_not_hold_for_the_fetch_dns_is_asked_again(inner, resolver):  # noqa: F811
    seen = inner(lambda r: ics())
    await fetch(URL)
    await fetch(URL)
    assert resolver.calls["cal.example"] == 2
    assert [r.url.host for r in seen] == [PUBLIC_IP, PUBLIC_IP]


async def test_cookies_not_carried(inner):  # noqa: F811
    def handler(request):
        if request.url.host == PUBLIC_IP:
            return httpx.Response(
                302, headers={"location": "https://b.example/x.ics", "set-cookie": "s=1; Path=/"}
            )
        return ics()

    seen = inner(handler)
    await fetch(URL)
    assert "cookie" not in seen[1].headers
    assert "cookie" not in seen[0].headers
