"""Addresses no setting can open: loopback, link-local, metadata and control endpoints, and every
IPv6 form that embeds one. The intranet switch only adds the private ranges."""

from __future__ import annotations

import ipaddress

import pytest
from sm_events.feeds.subscriptions import policy

ALWAYS_DENIED = [
    "127.0.0.1", "127.8.8.8", "::1", "0.0.0.0", "0.1.2.3", "::",  # loopback, unspecified
    "169.254.169.254", "169.254.170.2", "169.254.0.23", "fe80::1",  # link-local, ECS/GCP/AWS
    "224.0.0.1", "ff02::1", "255.255.255.255",  # multicast, broadcast
    "100.100.100.200",  # Alibaba, inside CGNAT
    "168.63.129.16",  # Azure wireserver, a public-looking address
    "192.0.0.192",  # Oracle
    "fd00:ec2::254", "fd00:ec2::1",  # AWS IPv6 service range, inside unique-local
    "fd00:c1::a9fe:a9fe", "fd20:ce::254",  # Oracle and GCP IPv6 metadata
    "fd12:3456::a9fe:a9fe", "fd99::7f00:1", "fdab::6464:64c8",  # the structural rule: embeds a denied IPv4
    "::ffff:169.254.169.254", "::ffff:100.100.100.200", "::ffff:127.0.0.1", "::ffff:168.63.129.16",
    "64:ff9b::a9fe:a9fe", "64:ff9b::6464:64c8", "2002:a9fe:a9fe::", "2002:6464:64c8::",
    "::169.254.169.254",
]  # fmt: skip
PRIVATE = [
    "10.1.2.3",
    "172.16.5.5",
    "192.168.1.1",
    "100.64.0.1",
    "fd12::1",
    "fd12:3456::1",
    "::ffff:10.0.0.1",
]
PUBLIC = ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]


def test_the_table_is_big_enough():
    assert len(ALWAYS_DENIED) >= 20


@pytest.mark.parametrize("address", ALWAYS_DENIED)
@pytest.mark.parametrize("switch", [False, True])
def test_always_denied(address, switch):
    assert not policy.address_allowed(ipaddress.ip_address(address), allow_private=switch)


@pytest.mark.parametrize("address", PRIVATE)
def test_private_only_with_the_switch(address):
    ip = ipaddress.ip_address(address)
    assert not policy.address_allowed(ip, allow_private=False)
    assert policy.address_allowed(ip, allow_private=True)


@pytest.mark.parametrize("address", PUBLIC)
def test_public_always(address):
    for switch in (False, True):
        assert policy.address_allowed(ipaddress.ip_address(address), allow_private=switch)


def test_the_denied_list_is_one_documented_constant():
    assert policy.ALWAYS_DENIED
    assert all(
        isinstance(net, ipaddress.IPv4Network | ipaddress.IPv6Network)
        for net in policy.ALWAYS_DENIED
    )
