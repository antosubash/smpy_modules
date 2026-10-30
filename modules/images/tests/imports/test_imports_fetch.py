"""``sm_images.imports.fetch.safe_stream``: pinned, re-validated, size-capped GETs.

The real connection layer is replaced by ``httpx.MockTransport`` (``inner``), and
DNS by ``resolver``; the request the mock sees is what would have gone on the
wire, so its URL host is the address dialled. ``test_imports_fetch_tls`` covers a
real socket and a real TLS handshake.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from sm_images.imports import fetch
from sm_images.imports.fetch import FetchTooLargeError, safe_stream
from sm_images.imports.url_safety import UnsafeURLError

from tests.support.fetch import OTHER_PUBLIC_IP, PUBLIC_IP, PUBLIC_IPV6, body


async def _fetch(url: str, *, max_bytes: int = 1_000_000, **kw) -> bytes:
    return b"".join(
        [chunk async for chunk in safe_stream(url, max_bytes=max_bytes, timeout=5, **kw)]
    )


async def test_connection_is_pinned_with_host_and_sni_intact(resolver, inner):
    resolver["cdn.example"] = [PUBLIC_IP]
    seen = inner(lambda r: body(b"img"))
    assert await _fetch("https://cdn.example/a.jpg?x=1") == b"img"
    (sent,) = seen
    assert sent.url.host == PUBLIC_IP
    assert sent.url.scheme == "https"
    assert sent.url.raw_path == b"/a.jpg?x=1"
    assert sent.headers["host"] == "cdn.example"
    assert sent.extensions["sni_hostname"] == "cdn.example"
    assert sent.headers["accept-encoding"] == "identity"


async def test_ipv6_address_is_pinned(resolver, inner):
    resolver["v6.example"] = [PUBLIC_IPV6]
    seen = inner(lambda r: body(b"x"))
    await _fetch("https://v6.example/a.jpg")
    assert seen[0].url.host == PUBLIC_IPV6
    assert seen[0].headers["host"] == "v6.example"


async def test_rejects_private_ip_after_dns(resolver, inner):
    resolver["evil.example"] = ["10.0.0.5"]
    seen = inner(lambda r: httpx.Response(200))
    with pytest.raises(UnsafeURLError, match="non_public_address"):
        await _fetch("http://evil.example/a.jpg")
    assert seen == []


async def test_redirect_to_private_rejected(resolver, inner):
    resolver["cdn.example"] = [PUBLIC_IP]
    resolver["internal.example"] = ["10.0.0.5"]
    seen = inner(
        lambda r: httpx.Response(302, headers={"location": "http://internal.example/secret"})
    )
    with pytest.raises(UnsafeURLError, match="non_public_address"):
        await _fetch("http://cdn.example/a.jpg")
    assert [r.url.host for r in seen] == [PUBLIC_IP]


@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://[::ffff:127.0.0.1]/",
        "file:///etc/passwd",
        "http://user:pw@img.example/b.jpg",
        "http://img.example:6379/",
    ],
)
async def test_redirect_target_is_revalidated(resolver, inner, location):
    resolver["cdn.example"] = [PUBLIC_IP]
    resolver["img.example"] = [OTHER_PUBLIC_IP]
    seen = inner(lambda r: httpx.Response(301, headers={"location": location}))
    with pytest.raises(UnsafeURLError):
        await _fetch("http://cdn.example/a.jpg")
    assert len(seen) == 1


async def test_malformed_redirect_location_fetches_nothing_more(resolver, inner):
    """httpx itself rejects it while building ``next_request``."""
    resolver["cdn.example"] = [PUBLIC_IP]
    seen = inner(lambda r: httpx.Response(302, headers={"location": "http://[::1/"}))
    with pytest.raises(httpx.RemoteProtocolError):
        await _fetch("http://cdn.example/a.jpg")
    assert len(seen) == 1


async def test_dns_rebinding_between_hops_is_caught(resolver, inner):
    """The same host answers public for hop 1 and private for hop 2."""
    resolver["rebind.example"] = [PUBLIC_IP]

    def handler(request):
        resolver["rebind.example"] = ["127.0.0.1"]
        return httpx.Response(302, headers={"location": "/next"})

    seen = inner(handler)
    with pytest.raises(UnsafeURLError, match="non_public_address"):
        await _fetch("http://rebind.example/a.jpg")
    assert len(seen) == 1


async def test_public_redirect_is_followed_and_pinned(resolver, inner):
    resolver["cdn.example"] = [PUBLIC_IP]
    resolver["img.example"] = [OTHER_PUBLIC_IP]

    def handler(request):
        if request.url.host == PUBLIC_IP:
            return httpx.Response(302, headers={"location": "https://img.example/b.jpg"})
        return body(b"ok")

    seen = inner(handler)
    assert await _fetch("http://cdn.example/a.jpg") == b"ok"
    assert [(r.url.host, r.headers["host"]) for r in seen] == [
        (PUBLIC_IP, "cdn.example"),
        (OTHER_PUBLIC_IP, "img.example"),
    ]
    assert seen[1].extensions["sni_hostname"] == "img.example"


async def test_at_most_five_redirects(resolver, inner):
    resolver["cdn.example"] = [PUBLIC_IP]
    seen = inner(lambda r: httpx.Response(302, headers={"location": "/again"}))
    with pytest.raises(UnsafeURLError, match="too_many_redirects"):
        await _fetch("http://cdn.example/a.jpg")
    assert len(seen) == 6  # the request and five redirects


async def test_one_redirect_too_many_takes_no_slot(resolver, inner):
    """The sixth redirect is refused before the hook: with the limiter busy it
    must not wait for (or take) a slot for a hop that will never be fetched."""
    resolver["cdn.example"] = [PUBLIC_IP]
    inner(lambda r: httpx.Response(302, headers={"location": "/again"}))
    entered: list[str] = []
    busy = asyncio.Event()  # never set: the next host's slot is never free

    async def on_redirect(target: httpx.URL) -> None:
        entered.append(str(target))
        if len(entered) > fetch.MAX_REDIRECTS:
            await busy.wait()

    with pytest.raises(UnsafeURLError, match="too_many_redirects"):
        await asyncio.wait_for(_fetch("http://cdn.example/a.jpg", on_redirect=on_redirect), 2)
    assert len(entered) == fetch.MAX_REDIRECTS


async def test_five_redirects_are_allowed(resolver, inner):
    resolver["cdn.example"] = [PUBLIC_IP]

    def handler(request):
        hop = int(request.url.params.get("n", "0"))
        if hop < 5:
            return httpx.Response(302, headers={"location": f"/r?n={hop + 1}"})
        return body(b"done")

    inner(handler)
    assert await _fetch("http://cdn.example/r") == b"done"


async def test_dead_first_address_falls_back_to_the_next(resolver, inner):
    resolver["dual.example"] = [PUBLIC_IPV6, PUBLIC_IP]

    def handler(request):
        if request.url.host == PUBLIC_IPV6:
            raise httpx.ConnectError("unreachable", request=request)
        return body(b"v4")

    seen = inner(handler)
    assert await _fetch("https://dual.example/a.jpg") == b"v4"
    assert [r.url.host for r in seen] == [PUBLIC_IPV6, PUBLIC_IP]


async def test_non_connect_errors_do_not_try_other_addresses(resolver, inner):
    resolver["slow.example"] = [PUBLIC_IP, OTHER_PUBLIC_IP]

    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    seen = inner(handler)
    with pytest.raises(httpx.ReadTimeout):
        await _fetch("http://slow.example/a.jpg")
    assert len(seen) == 1


async def test_oversize_stream_aborted(resolver, inner):
    """No Content-Length: the cap is enforced on the bytes actually received."""
    resolver["cdn.example"] = [PUBLIC_IP]

    async def body():
        for _ in range(100):
            yield b"x" * 1024

    inner(lambda r: httpx.Response(200, content=body()))
    got = 0
    with pytest.raises(FetchTooLargeError):
        async for chunk in safe_stream("http://cdn.example/a.jpg", max_bytes=10_000, timeout=5):
            got += len(chunk)
    assert got <= 10_000


async def test_declared_oversize_is_refused_before_reading(resolver, inner):
    resolver["cdn.example"] = [PUBLIC_IP]
    inner(lambda r: httpx.Response(200, headers={"content-length": "20000"}, content=b"x" * 20000))
    with pytest.raises(FetchTooLargeError):
        async for _ in safe_stream("http://cdn.example/a.jpg", max_bytes=10_000, timeout=5):
            pytest.fail("a declared-oversize body must not be streamed")


async def test_exactly_max_bytes_is_accepted(resolver, inner):
    resolver["cdn.example"] = [PUBLIC_IP]
    inner(lambda r: body(b"y" * 10_000))
    assert len(await _fetch("http://cdn.example/a.jpg", max_bytes=10_000)) == 10_000


async def test_compressed_response_is_refused(resolver, inner):
    """Bytes are counted as delivered; a decoder in between would be a bomb vector."""
    resolver["cdn.example"] = [PUBLIC_IP]
    inner(lambda r: httpx.Response(200, headers={"content-encoding": "gzip"}, content=b"\x1f\x8b"))
    with pytest.raises(fetch.FetchError, match="unsupported_encoding"):
        await _fetch("http://cdn.example/a.jpg")


@pytest.mark.parametrize("status", [404, 429, 500, 503])
async def test_error_status_raises_with_the_response(resolver, inner, status):
    resolver["cdn.example"] = [PUBLIC_IP]
    inner(lambda r: httpx.Response(status, headers={"retry-after": "7"}))
    with pytest.raises(httpx.HTTPStatusError) as caught:
        await _fetch("http://cdn.example/a.jpg")
    assert caught.value.response.status_code == status
    assert caught.value.response.headers["retry-after"] == "7"


async def test_redirect_without_location_is_an_error(resolver, inner):
    resolver["cdn.example"] = [PUBLIC_IP]
    inner(lambda r: httpx.Response(302))
    with pytest.raises(httpx.HTTPStatusError):
        await _fetch("http://cdn.example/a.jpg")


async def test_proxy_env_cannot_route_around_the_pin(resolver, inner, monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(name, "http://10.0.0.1:3128")
    resolver["cdn.example"] = [PUBLIC_IP]
    seen = inner(lambda r: body(b"ok"))
    assert await _fetch("https://cdn.example/a.jpg") == b"ok"
    assert seen[0].url.host == PUBLIC_IP
