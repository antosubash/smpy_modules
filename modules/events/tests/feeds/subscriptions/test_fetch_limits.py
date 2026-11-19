"""What a hostile or broken server may do: wrong types, big or endless bodies, bombs, slow drips.
Every one ends as a coded failure within the deadline. Fake DNS and connection layer only."""

from __future__ import annotations

import asyncio
import time
import zlib

import httpx
import pytest

from tests.support.net import (  # noqa: F401 - fixtures
    ICS,
    PUBLIC_IP,
    body,
    failure_code,
    fetch,
    ics,
    inner,
    resolver,
)

URL = "https://cal.example/feed.ics"


@pytest.fixture(autouse=True)
def _host(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP]


async def test_html_refused(inner):  # noqa: F811
    inner(lambda r: body(b"<html>sign in</html>", **{"content-type": "text/html; charset=utf-8"}))
    assert await failure_code(URL) == "unexpected_content_type"


@pytest.mark.parametrize("kind", ["application/json", "image/png", "text/xml", "application/pdf"])
async def test_other_types_refused(inner, kind):  # noqa: F811
    inner(lambda r: body(ICS, **{"content-type": kind}))
    assert await failure_code(URL) == "unexpected_content_type"


async def test_missing_content_type_sniffed(inner):  # noqa: F811
    inner(lambda r: body(b"<html>hello</html>"))
    assert await failure_code(URL) == "ics_invalid"
    inner(lambda r: body(ICS))
    assert (await fetch(URL)).body == ICS


async def test_empty_and_garbage_bodies_are_not_calendars(inner):  # noqa: F811
    for payload in (b"", b"\x00\x01\x02", b"BEGIN:VEVENT\r\nEND:VEVENT\r\n", b"just some text"):
        inner(lambda r, payload=payload: body(payload, **{"content-type": "text/plain"}))
        assert await failure_code(URL) == "ics_invalid"


@pytest.mark.parametrize(
    "media",
    [
        "text/calendar",
        "text/calendar; charset=utf-8",
        "TEXT/Calendar; method=PUBLISH",
        "text/plain",
        "text/plain;charset=UTF-8",
        "application/octet-stream",
        "application/ics",
        "text/x-vcalendar",
        "",
    ],
)
async def test_accepted_media_types(inner, media):  # noqa: F811
    inner(lambda r: body(ICS, **({"content-type": media} if media else {})))
    assert (await fetch(URL)).body == ICS


def _bomb_chunks(seen: list[int]):
    """10 KB of gzip that inflates to a gigabyte, built with ``zlib`` streaming: neither the
    test nor the code under test ever holds the inflated bytes."""
    compressor = zlib.compressobj(9, zlib.DEFLATED, 31)
    zeros = b"\x00" * (1 << 20)
    out = b""
    for _ in range(1024):
        out += compressor.compress(zeros)
    out += compressor.flush()

    async def chunks():
        for start in range(0, len(out), 2048):
            seen.append(start)
            yield out[start : start + 2048]

    return chunks, len(out)


async def test_encoded_body_refused(inner):  # noqa: F811
    seen: list[int] = []
    chunks, size = _bomb_chunks(seen)
    assert size < 2_000_000
    inner(lambda r: httpx.Response(200, headers={"content-encoding": "gzip"}, content=chunks()))
    assert await failure_code(URL) == "unsupported_encoding"
    assert seen == []  # not one byte of it was read, let alone inflated


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "zstd", "gzip, br"])
async def test_every_content_encoding_is_refused(inner, encoding):  # noqa: F811
    inner(lambda r: body(ICS, **{"content-encoding": encoding}))
    assert await failure_code(URL) == "unsupported_encoding"
    inner(lambda r: body(ICS, **{"content-encoding": "identity"}))
    assert (await fetch(URL)).body == ICS


async def test_declared_length_over_cap_refused_before_read(inner):  # noqa: F811
    iterated: list[int] = []

    async def chunks():
        iterated.append(1)
        yield ICS

    inner(lambda r: httpx.Response(200, headers={"content-length": "1000000"}, content=chunks()))
    assert await failure_code(URL, max_bytes=10_000) == "too_large"
    assert iterated == []


async def test_body_cap_streams(inner):  # noqa: F811
    sent = {"bytes": 0}

    async def endless():
        while True:
            sent["bytes"] += 1024
            yield b"X" * 1024

    inner(
        lambda r: httpx.Response(200, headers={"transfer-encoding": "chunked"}, content=endless())
    )
    started = time.monotonic()
    assert await failure_code(URL, max_bytes=10_000) == "too_large"
    assert sent["bytes"] <= 10_000 + 2 * 1024  # cut at the cap plus the chunk that crossed it
    assert time.monotonic() - started < 2


async def test_a_lying_content_length_is_cut_at_the_cap(inner):  # noqa: F811
    big = ICS + b"X" * 50_000
    inner(lambda r: body(big, **{"content-length": "10"}))
    assert await failure_code(URL, max_bytes=10_000) == "too_large"


async def test_a_garbage_content_length_is_ignored(inner):  # noqa: F811
    inner(lambda r: body(ICS, **{"content-length": "not-a-number"}))
    assert (await fetch(URL)).body == ICS


async def test_exactly_cap_accepted(inner):  # noqa: F811
    exact = ICS + b"X" * (10_000 - len(ICS))
    inner(lambda r: body(exact))
    assert len((await fetch(URL, max_bytes=10_000)).body) == 10_000
    inner(lambda r: body(exact + b"X"))
    assert await failure_code(URL, max_bytes=10_000) == "too_large"


async def test_the_body_is_returned_as_delivered(inner):  # noqa: F811
    payload = ICS + "SUMMARY:Kaffee ☕\r\n".encode()
    inner(lambda r: body(payload))
    assert (await fetch(URL)).body == payload


async def test_deadline_covers_slow_body(inner):  # noqa: F811
    async def drip():
        yield ICS
        while True:
            await asyncio.sleep(0.2)
            yield b"X"

    inner(lambda r: httpx.Response(200, content=drip()))
    started = time.monotonic()
    assert await failure_code(URL, timeout=0.6) == "timeout"
    assert time.monotonic() - started < 1.6


async def test_deadline_covers_slow_headers(inner):  # noqa: F811
    async def slow(request):
        await asyncio.sleep(30)
        return ics()

    inner(slow)
    started = time.monotonic()
    assert await failure_code(URL, timeout=0.3) == "timeout"
    assert time.monotonic() - started < 1.3


async def test_one_deadline_covers_every_hop(inner):  # noqa: F811
    async def slow_redirect(request):
        await asyncio.sleep(0.25)
        return httpx.Response(302, headers={"location": URL})

    inner(slow_redirect)
    started = time.monotonic()
    assert await failure_code(URL, timeout=0.6) == "timeout"
    assert time.monotonic() - started < 1.6


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (httpx.ConnectError("refused"), "connect_failed"),
        (httpx.ConnectTimeout("slow"), "timeout"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ReadError("reset"), "connect_failed"),
        (httpx.RemoteProtocolError("bad"), "connect_failed"),
    ],
)
async def test_network_errors_mapped(inner, error, code):  # noqa: F811
    def handler(request):
        raise error

    inner(handler)
    assert await failure_code(URL) == code


async def test_tls_errors_mapped(inner):  # noqa: F811
    import ssl

    def handler(request):
        try:
            raise ssl.SSLCertVerificationError("certificate verify failed")
        except ssl.SSLError as cause:
            raise httpx.ConnectError("tls") from cause

    inner(handler)
    assert await failure_code(URL) == "tls_failed"


async def test_a_body_that_dies_midway_is_a_connection_failure(inner):  # noqa: F811
    async def dies():
        yield ICS
        raise httpx.ReadError("connection reset")

    inner(lambda r: httpx.Response(200, headers={"content-type": "text/calendar"}, content=dies()))
    assert await failure_code(URL) == "connect_failed"


@pytest.mark.parametrize(
    ("sent", "kept"),
    [
        ('"abc"', '"abc"'),
        ('W/"weak"', 'W/"weak"'),
        ("x" * 200, "x" * 200),
        ("x" * 201, None),
        ("tab\there", None),
        ("", None),
    ],
)
async def test_etag_is_kept_only_when_short_printable_ascii(inner, sent, kept):  # noqa: F811
    inner(lambda r: ics(etag=sent) if sent else ics())
    assert (await fetch(URL)).etag == kept


async def test_last_modified_is_capped(inner):  # noqa: F811
    inner(lambda r: ics(**{"last-modified": "L" * 64}))
    assert (await fetch(URL)).last_modified == "L" * 64
    inner(lambda r: ics(**{"last-modified": "L" * 65}))
    assert (await fetch(URL)).last_modified is None


async def test_a_refused_internal_address_and_an_unresolvable_host_look_the_same(inner):  # noqa: F811
    inner(lambda r: ics())
    # cal.example is public; these two are not in the table (unresolvable) and private.
    codes = {await failure_code("https://nowhere.example/x.ics")}
    codes.add(await failure_code("https://10.0.0.5/x.ics"))
    codes.add(await failure_code("https://[::1]/x.ics"))
    assert codes == {"url_unreachable"}


async def test_a_bad_address_fails_before_anything_is_dialled(inner):  # noqa: F811
    seen = inner(lambda r: ics())
    for url in ("ftp://cal.example/x", "https://u:p@cal.example/", "https://cal.example:8443/", ""):
        assert (await failure_code(url)).startswith("url_")
    assert await failure_code("http://cal.example/x.ics") == "url_scheme"
    assert seen == []
