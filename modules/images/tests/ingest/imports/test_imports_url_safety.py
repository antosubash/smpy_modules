"""``sm_images.ingest.imports.url_safety``: the SSRF guard (portal ``download_security``).

A URL is fetchable only when its scheme is http(s), its port is 80/443, it has
no userinfo, and *every* address its host resolves to is public. Resolution is
monkeypatched (``resolver``), so nothing here touches the network.
"""

from __future__ import annotations

import pytest
from sm_images.ingest.imports import url_safety
from sm_images.ingest.imports.url_safety import UnsafeURLError, is_public_address, resolve_public

from tests.support.fetch import PUBLIC_IP, PUBLIC_IPV6


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.5",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "169.254.1.1",
        "100.64.0.1",  # CGNAT
        "100.127.255.254",
        "198.18.0.1",  # benchmarking
        "198.19.255.255",
        "0.0.0.0",
        "224.0.0.1",
        "240.0.0.1",
        "255.255.255.255",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "fd00:ec2::254",  # AWS IMDSv6
        "ff02::1",
        "fe80::1%eth0",
    ],
)
def test_rejects_private_ip_after_dns(resolver, address):
    resolver["evil.example"] = [address]
    with pytest.raises(UnsafeURLError, match="non_public_address"):
        resolve_public("http://evil.example/a.jpg")


@pytest.mark.parametrize(
    "address",
    [
        "::ffff:127.0.0.1",  # IPv4-mapped
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
        "::ffff:100.64.0.1",
        "::7f00:1",  # IPv4-compatible (deprecated)
        "64:ff9b::7f00:1",  # NAT64
        "64:ff9b::a9fe:a9fe",
        "2002:7f00:1::1",  # 6to4
        "2002:a00:1::1",
        "2001:0:4136:e378:8000:63bf:80ff:fffe",  # Teredo, client 127.0.0.1
    ],
)
def test_ipv6_mapped_v4_rejected(resolver, address):
    resolver["evil.example"] = [address]
    with pytest.raises(UnsafeURLError, match="non_public_address"):
        resolve_public("https://evil.example/a.jpg")


@pytest.mark.parametrize(
    "url", ["http://[::ffff:127.0.0.1]/", "http://[::1]/", "http://127.0.0.1/"]
)
def test_ip_literals_are_checked_too(url):
    with pytest.raises(UnsafeURLError, match="non_public_address"):
        resolve_public(url)


@pytest.mark.parametrize("host", ["2130706433", "0x7f.1", "0177.0.0.1", "127.1", "localhost"])
def test_non_canonical_loopback_forms_are_rejected(host):
    """Forms inet_aton accepts mean 127.0.0.1; the real resolver must catch them."""
    with pytest.raises(UnsafeURLError):
        resolve_public(f"http://{host}/")


def test_any_private_address_among_many_is_rejected(resolver):
    resolver["mixed.example"] = [PUBLIC_IP, "127.0.0.1"]
    with pytest.raises(UnsafeURLError, match="non_public_address"):
        resolve_public("https://mixed.example/a.jpg")


def test_public_host_returns_every_address_once_in_order(resolver):
    resolver["dual.example"] = [PUBLIC_IPV6, PUBLIC_IP, PUBLIC_IP]
    assert resolve_public("https://dual.example/a.jpg") == (
        "dual.example",
        (PUBLIC_IPV6, PUBLIC_IP),
    )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://cdn.example/a.jpg",
        "file:///etc/passwd",
        "gopher://x/",
        "//x/a.jpg",
        "javascript:alert(1)",
    ],
)
def test_non_http_schemes_are_rejected(resolver, url):
    resolver["cdn.example"] = [PUBLIC_IP]
    with pytest.raises(UnsafeURLError, match="invalid_scheme"):
        resolve_public(url)


@pytest.mark.parametrize(
    "url", ["http://user@cdn.example/", "https://u:p@cdn.example/a.jpg", "http://:@cdn.example/"]
)
def test_userinfo_is_rejected(resolver, url):
    resolver["cdn.example"] = [PUBLIC_IP]
    with pytest.raises(UnsafeURLError, match="userinfo_not_allowed"):
        resolve_public(url)


@pytest.mark.parametrize("port", [22, 25, 2375, 5432, 6379, 8080, 8443, 9000])
def test_only_web_ports_are_allowed(resolver, port):
    resolver["cdn.example"] = [PUBLIC_IP]
    with pytest.raises(UnsafeURLError, match="port_not_allowed"):
        resolve_public(f"http://cdn.example:{port}/a.jpg")


@pytest.mark.parametrize(
    "url", ["http://cdn.example:80/", "https://cdn.example:443/", "https://cdn.example/"]
)
def test_default_ports_are_allowed(resolver, url):
    resolver["cdn.example"] = [PUBLIC_IP]
    assert resolve_public(url) == ("cdn.example", (PUBLIC_IP,))


def test_allowed_ports_can_be_widened_explicitly(resolver):
    resolver["cdn.example"] = [PUBLIC_IP]
    assert (
        resolve_public("http://cdn.example:8080/", allowed_ports=frozenset({8080}))[0]
        == "cdn.example"
    )


@pytest.mark.usefixtures("resolver")
def test_unresolvable_host_fails_closed():
    with pytest.raises(UnsafeURLError, match="unresolvable_host"):
        resolve_public("http://minio/bucket/a.jpg")


def test_resolver_error_fails_closed(monkeypatch):
    def broken(*_a, **_k):
        raise OSError("resolver exploded")

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", broken)
    with pytest.raises(UnsafeURLError, match="unresolvable_host"):
        resolve_public("http://cdn.example/a.jpg")


def test_empty_resolution_fails_closed(monkeypatch):
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", lambda *_a, **_k: [])
    with pytest.raises(UnsafeURLError, match="unresolvable_host"):
        resolve_public("http://cdn.example/a.jpg")


def test_unparsable_resolved_address_fails_closed(resolver):
    resolver["weird.example"] = ["not-an-ip"]
    with pytest.raises(UnsafeURLError, match="non_public_address"):
        resolve_public("http://weird.example/a.jpg")


@pytest.mark.parametrize("url", ["http://", "http:///path", "not a url", "", "http://[::1/"])
def test_malformed_urls_fail_closed(url):
    with pytest.raises(UnsafeURLError):
        resolve_public(url)


def test_error_message_is_a_constant_code():
    """The message is stored on an import row and shown: it never echoes the URL."""
    with pytest.raises(UnsafeURLError) as caught:
        resolve_public("ftp://secret-host.internal/token=abc")
    assert caught.value.code == "invalid_scheme"
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("address", [PUBLIC_IP, PUBLIC_IPV6, "8.8.8.8", "2001:4860:4860::8888"])
def test_public_addresses_are_public(address):
    import ipaddress

    assert is_public_address(ipaddress.ip_address(address))
