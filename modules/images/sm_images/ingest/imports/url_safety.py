"""The SSRF guard for server-side fetches of user-supplied URLs.

Ported from the portal's ``download_security`` (resolve, require every address
public, fail closed) and ``smpy_gis``'s ``url_safety`` (the metadata addresses).

A URL is fetchable only when its scheme is http(s), its port is allowed (80 and
443 by default), it carries no userinfo, and **every** address its host resolves
to is public. A hostname or literal check alone is not enough: ``localhost``,
``127.0.0.1.nip.io``, ``http://2130706433/`` and ``[::ffff:10.0.0.1]`` all reach
internal addresses. The resolved addresses are what :mod:`sm_images.ingest.imports.fetch`
then dials, so the check and the connection cannot disagree (DNS rebinding).

The URL is parsed with httpx, the parser that later builds the request, so the
host that is validated is the host that would be dialled.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Final

import httpx

__all__ = [
    "DEFAULT_ALLOWED_PORTS",
    "UnsafeURLError",
    "check_url",
    "is_public_address",
    "resolve_public",
]

logger = logging.getLogger(__name__)

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

ALLOWED_SCHEMES: Final = frozenset({"http", "https"})
DEFAULT_ALLOWED_PORTS: Final = frozenset({80, 443})
_DEFAULT_PORTS: Final = {"http": 80, "https": 443}

# Blocked even where the stdlib flags disagree between Python versions. The
# flags already cover most of these; listing them keeps the policy explicit.
_BLOCKED_NETWORKS: Final = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "100.64.0.0/10",  # CGNAT (shared address space)
        "169.254.0.0/16",  # link-local, incl. 169.254.169.254 metadata
        "192.0.0.0/24",
        "198.18.0.0/15",  # benchmarking
        "::/96",  # IPv4-compatible (deprecated)
        "fc00::/7",  # unique local, incl. fd00:ec2::254 metadata
        "fe80::/10",
    )
)
_METADATA: Final = frozenset(ipaddress.ip_address(a) for a in ("169.254.169.254", "fd00:ec2::254"))
# RFC 6052 NAT64 well-known prefix and the deprecated IPv4-compatible block: in
# both the low 32 bits are an IPv4 address.
_NAT64: Final = ipaddress.IPv6Network("64:ff9b::/96")
_V4_COMPATIBLE: Final = ipaddress.IPv6Network("::/96")


class UnsafeURLError(ValueError):
    """A URL that must not be fetched. ``code`` (also the message) is a constant
    safe to store and show; it never echoes the URL."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """The IPv4 addresses an IPv6 address maps, translates or tunnels to."""
    found: list[ipaddress.IPv4Address] = []
    if ip.ipv4_mapped is not None:
        found.append(ip.ipv4_mapped)
    if ip in _NAT64 or ip in _V4_COMPATIBLE:
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if ip.sixtofour is not None:
        found.append(ip.sixtofour)
    if ip.teredo is not None:
        found.extend(ip.teredo)
    return found


def is_public_address(ip: IPAddress) -> bool:
    """Whether ``ip`` is publicly routable in every sense.

    ``is_global`` alone misses multicast and does not look inside IPv6 forms
    that embed an IPv4 address, so an embedded address must be public too.
    """
    if isinstance(ip, ipaddress.IPv6Address) and any(
        not is_public_address(v4) for v4 in _embedded_ipv4(ip)
    ):
        return False
    if ip in _METADATA or any(ip in net for net in _BLOCKED_NETWORKS if net.version == ip.version):
        return False
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local)
    ):
        return False
    return ip.is_global


def check_url(
    url: str | httpx.URL, *, allowed_ports: frozenset[int] = DEFAULT_ALLOWED_PORTS
) -> tuple[str, int]:
    """The syntactic half of the guard: scheme, userinfo, host and port.

    Returns ``(host, port)``. Raises :class:`UnsafeURLError`; never resolves.
    """
    try:
        parsed = url if isinstance(url, httpx.URL) else httpx.URL(url.strip())
    except (httpx.InvalidURL, TypeError, ValueError) as error:
        raise UnsafeURLError("invalid_url") from error
    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError("invalid_scheme")
    if parsed.userinfo:
        raise UnsafeURLError("userinfo_not_allowed")
    try:
        host = parsed.raw_host.decode("ascii")
    except UnicodeDecodeError as error:
        raise UnsafeURLError("invalid_url") from error
    if not host:
        raise UnsafeURLError("missing_host")
    if parsed.port == 0:
        raise UnsafeURLError("invalid_url")
    port = parsed.port or _DEFAULT_PORTS[scheme]
    if port not in allowed_ports:
        raise UnsafeURLError("port_not_allowed")
    return host, port


def _parse_ip(address: str) -> IPAddress:
    """A resolved address without its IPv6 zone id; unparsable fails closed."""
    try:
        return ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError as error:
        raise UnsafeURLError("non_public_address") from error


def resolve_public(
    url: str | httpx.URL, *, allowed_ports: frozenset[int] = DEFAULT_ALLOWED_PORTS
) -> tuple[str, tuple[str, ...]]:
    """Resolve ``url``'s host and require every address to be public.

    Returns ``(host, ips)``: the host as it goes in the Host header and SNI, and
    each distinct address in resolver order - the only addresses a fetch may
    dial. Blocking (``getaddrinfo``); call it through ``asyncio.to_thread``.

    Raises:
        UnsafeURLError: bad scheme, userinfo, port or host; unresolvable; or any
            address not public. Every failure path raises (fails closed).
    """
    host, port = check_url(url, allowed_ports=allowed_ports)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as error:
        raise UnsafeURLError("unresolvable_host") from error
    if not infos:
        raise UnsafeURLError("unresolvable_host")
    ips: list[str] = []
    for info in infos:
        ip = _parse_ip(str(info[4][0]))
        if not is_public_address(ip):
            logger.warning(
                "Blocked fetch of a non-public address",
                extra={"host": host, "resolved_ip": str(ip)},
            )
            raise UnsafeURLError("non_public_address")
        if str(ip) not in ips:
            ips.append(str(ip))
    return host, tuple(ips)
