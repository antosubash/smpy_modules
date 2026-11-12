"""The address rules a base URL must pass (#347), on literals and resolved names."""

from __future__ import annotations

import ipaddress

import pytest
from sm_ai.core.url_safety import (
    UnsafeURLError,
    check_url,
    is_public_address,
    literal_address,
    resolve_public,
)

from tests.support.ai_test_stubs import fake_dns

NOT_PUBLIC = [
    "127.0.0.1",
    "10.0.0.5",
    "172.16.3.4",
    "192.168.1.10",
    "169.254.169.254",  # cloud metadata
    "100.64.0.1",  # CGNAT
    "0.0.0.0",
    "224.0.0.1",  # multicast
    "240.0.0.1",  # reserved
    "198.18.0.1",
    "::1",
    "::",
    "fc00::1",
    "fd00:ec2::254",  # metadata over IPv6
    "fe80::1",
    "ff02::1",
    "::ffff:10.0.0.1",  # IPv4-mapped
    "64:ff9b::7f00:1",  # NAT64 of 127.0.0.1
    "2002:7f00:1::",  # 6to4 of 127.0.0.1
    "2001:0:4136:e378:8000:63bf:f5ff:fffe",  # Teredo, client 10.0.0.1
]
PUBLIC = ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111", "::ffff:93.184.216.34"]


@pytest.mark.parametrize("address", NOT_PUBLIC)
def test_non_public_addresses_refused(address):
    assert is_public_address(ipaddress.ip_address(address)) is False


@pytest.mark.parametrize("address", PUBLIC)
def test_public_addresses_allowed(address):
    assert is_public_address(ipaddress.ip_address(address)) is True


class TestCheckUrl:
    @pytest.mark.parametrize(
        ("url", "code"),
        [
            ("ftp://example.com/", "invalid_scheme"),
            ("file:///etc/passwd", "invalid_scheme"),
            ("https://user:pw@example.com/v1", "userinfo_not_allowed"),
            ("http:///v1", "missing_host"),
            ("not a url", "invalid_scheme"),
        ],
    )
    def test_refused(self, url, code):
        with pytest.raises(UnsafeURLError) as caught:
            check_url(url)
        assert caught.value.code == code

    def test_any_port_is_allowed(self):
        # A provider endpoint is not an arbitrary download: vLLM listens on 8000.
        assert check_url("http://gateway.example:8000/v1") == ("gateway.example", 8000)
        assert check_url("https://api.example.com/v1") == ("api.example.com", 443)


def test_literal_address():
    assert literal_address("127.0.0.1") == ipaddress.ip_address("127.0.0.1")
    assert literal_address("[::1]") == ipaddress.ip_address("::1")
    assert literal_address("vllm.local") is None


class TestResolvePublic:
    def test_every_address_must_be_public(self, monkeypatch):
        fake_dns(monkeypatch, {"mixed.example": ["93.184.216.34", "10.0.0.5"]})
        with pytest.raises(UnsafeURLError) as caught:
            resolve_public("https://mixed.example/v1")
        assert caught.value.code == "non_public_address"

    def test_a_name_for_a_private_address_is_refused(self, monkeypatch):
        fake_dns(monkeypatch, {"vllm": ["10.1.2.3"]})
        with pytest.raises(UnsafeURLError, match="non_public_address"):
            resolve_public("http://vllm:8000/v1")

    def test_unresolvable(self, monkeypatch):
        fake_dns(monkeypatch, {})
        with pytest.raises(UnsafeURLError, match="unresolvable_host"):
            resolve_public("https://nowhere.example/v1")

    def test_public_name_returns_its_addresses(self, monkeypatch):
        fake_dns(monkeypatch, {"api.example": ["93.184.216.34", "93.184.216.34", "8.8.8.8"]})
        assert resolve_public("https://api.example/v1") == (
            "api.example",
            ("93.184.216.34", "8.8.8.8"),
        )
