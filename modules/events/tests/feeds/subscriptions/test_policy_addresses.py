"""The address guard: every non-public address class refused, the intranet switch narrower."""

from __future__ import annotations

import ipaddress

import pytest
from sm_events.feeds.subscriptions import policy
from sm_events.feeds.subscriptions.url_safety import UnsafeURLError

from tests.support.net import resolver  # noqa: F401 - fixture

OFF = policy.Policy(allow_private=False)


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(UnsafeURLError) as caught:
        fn(*args, **kwargs)
    return caught.value.code


def _url(raw: str):
    import httpx

    return httpx.URL(raw)


# --- the address guard -------------------------------------------------------

PRIVATE_OR_WORSE = [
    # loopback
    "127.0.0.1",
    "127.255.255.254",
    "::1",
    # RFC 1918
    "10.0.0.1",
    "10.1.2.3",
    "10.255.255.255",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.0.1",
    "192.168.1.1",
    # link-local, including the cloud metadata addresses
    "169.254.169.254",
    "169.254.0.1",
    "fe80::1",
    "febf::1",
    # CGNAT, benchmarking, "this network", protocol assignments
    "100.64.0.1",
    "100.127.255.255",
    "198.18.0.1",
    "198.19.255.255",
    "0.0.0.0",
    "0.1.2.3",
    "192.0.0.1",
    # multicast, broadcast, reserved
    "224.0.0.1",
    "239.255.255.255",
    "ff02::1",
    "ff00::1",
    "255.255.255.255",
    "240.0.0.1",
    # documentation ranges
    "192.0.2.1",
    "198.51.100.7",
    "203.0.113.9",
    "2001:db8::1",
    # unspecified, unique-local (including the EC2 metadata address), site-local
    "::",
    "fc00::1",
    "fd00:ec2::254",
    "fdff::1",
    "fec0::1",
    # IPv4-mapped and -compatible forms of the above
    "::ffff:127.0.0.1",
    "::ffff:10.0.0.1",
    "::ffff:169.254.169.254",
    "::ffff:7f00:1",
    "::127.0.0.1",
    "::10.0.0.1",
    # NAT64, 6to4 and Teredo forms that embed a private IPv4
    "64:ff9b::a9fe:a9fe",
    "64:ff9b::7f00:1",
    "64:ff9b::a00:1",
    "2002:7f00:0001::",
    "2002:a00:1::",
    "2002:a9fe:a9fe::",
    "2001:0:4136:e378:8000:63bf:f5ff:fffe",  # Teredo, client 10.0.0.1
]

PUBLIC = [
    "93.184.216.34",
    "8.8.8.8",
    "1.1.1.1",
    "2606:2800:220:1:248:1893:25c8:1946",
    "2001:4860:4860::8888",
    "::ffff:8.8.8.8",
]


def test_the_matrix_is_large_enough_and_covers_both_families():
    assert len(PRIVATE_OR_WORSE) >= 40
    families = {ipaddress.ip_address(a).version for a in PRIVATE_OR_WORSE}
    assert families == {4, 6}


@pytest.mark.parametrize("address", PRIVATE_OR_WORSE)
def test_address_matrix(address):
    assert policy.address_allowed(ipaddress.ip_address(address), allow_private=False) is False


def test_a_nat64_address_is_refused_even_when_it_embeds_a_public_ipv4():
    """The guard is conservative: a translator prefix is not a place a calendar lives."""
    ip = ipaddress.ip_address("64:ff9b::808:808")
    assert not policy.address_allowed(ip, allow_private=False)


@pytest.mark.parametrize("address", PUBLIC)
def test_public_addresses_pass(address):
    for switch in (False, True):
        assert policy.address_allowed(ipaddress.ip_address(address), allow_private=switch)


@pytest.mark.parametrize(
    "address",
    [
        "10.1.2.3",
        "10.0.0.1",
        "172.16.5.5",
        "192.168.1.1",
        "fd12::1",
        "fc00::1",
        "100.64.0.1",
        "198.18.0.1",
        "::ffff:10.0.0.1",
        "64:ff9b::a00:1",
    ],
)
def test_intranet_switch_opens_private_ranges_only(address):
    assert policy.address_allowed(ipaddress.ip_address(address), allow_private=True)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.1.2.3",
        "::1",
        "169.254.169.254",
        "169.254.1.1",
        "fd00:ec2::254",
        "fe80::1",
        "0.0.0.0",
        "::",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "64:ff9b::7f00:1",
        "64:ff9b::a9fe:a9fe",
        "2002:7f00:1::",
        "224.0.0.1",
        "ff02::1",
        "240.0.0.1",
        "255.255.255.255",
        "fec0::1",
        "192.0.0.1",
        "192.0.2.1",
        "2001:db8::1",
    ],
)
def test_intranet_switch_never_opens_loopback_or_metadata(address):
    assert not policy.address_allowed(ipaddress.ip_address(address), allow_private=True)


# --- literal hosts -----------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://[::ffff:7f00:1]/",
        "https://[::1]/",
        "https://[fe80::1]/",
        "https://127.0.0.1/",
        "https://10.0.0.5/",
        "https://169.254.169.254/latest/meta-data/",
        "https://[64:ff9b::a9fe:a9fe]/",
        "https://[fd00:ec2::254]/",
        "https://2130706433/",  # 127.0.0.1 as one integer
        "https://0x7f.1/",
        "https://0x7f000001/",
        "https://127.1/",
        "https://017700000001/",
        "https://010.0.0.1/",  # octal for 8.0.0.1 to some resolvers
        "https://0/",
    ],
)
def test_literal_hosts(url, resolver):  # noqa: F811
    """Refused before any lookup (the resolver would answer these names itself)."""
    try:
        normalised = policy.normalise(url)
    except UnsafeURLError as refused:
        assert refused.code == "invalid_url"
    else:
        code = _code(policy.resolve_allowed, _url(normalised), OFF)
        assert code in {"non_public_address", "invalid_url"}
    assert resolver.calls == {}
