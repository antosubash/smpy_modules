"""Events' rules for a subscription address, over the shared address guard.

Checked on save **and** again on every fetch and every redirect hop, because DNS changes:

- one normal form (:func:`normalise`): ``webcal://`` is ``https://``, the fragment goes, the host
  is IDNA ASCII, the whole is at most ``SUBSCRIPTION_URL_MAX`` characters;
- ``https`` only, no credentials, only the scheme's default port (:func:`check`);
- **every** address the host resolves to must be publicly routable (:func:`resolve_allowed`),
  literal IPs and the many spellings of 127.0.0.1 (``2130706433``, ``0x7f.1``) included.

The *intranet switch* (``allow_private_subscription_urls``) is deliberately narrower than ai's,
which skips the address check altogether: it lets RFC 1918, unique-local, CGNAT and benchmarking
addresses through (plus ``http`` and any port), and **never** anything in :data:`ALWAYS_DENIED`:
loopback, link-local, multicast and the cloud metadata and control endpoints (even those inside
the opened ranges), nor an IPv4-mapped, NAT64, 6to4 or Teredo form of one
(:func:`address_allowed`).
It is a SYSTEM setting written on the Settings screen (``settings.edit``), never per calendar.
Using it also needs ``events.manage``: a save by anyone else is judged as if the switch
were off (:class:`Policy.may_use_private`).

Every refusal is an :class:`UnsafeURLError` whose message is its code and nothing else.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass
from typing import Final

import httpx
import idna

from sm_events.core import constants
from sm_events.feeds.subscriptions import url_safety
from sm_events.feeds.subscriptions.url_safety import (
    IPAddress,
    UnsafeURLError,
    _embedded_ipv4,
    _parse_ip,
    is_public_address,
)

__all__ = [
    "ALWAYS_DENIED",
    "Policy",
    "address_allowed",
    "check",
    "effective",
    "flag_after_save",
    "normalise",
    "resolve_allowed",
    "user_code",
]

logger = logging.getLogger(__name__)

_WEBCAL: Final = re.compile(r"^webcals?://", re.IGNORECASE)
_DEFAULT_PORT: Final = {"http": 80, "https": 443}
_ANY_PORT: Final = frozenset(range(1, 65536))
_NUMERIC_HOST: Final = re.compile(r"^(?:0x[0-9a-f]+|\d+)(?:\.(?:0x[0-9a-f]+|\d+))*$", re.IGNORECASE)
"""A host made only of numbers: a resolver reads ``2130706433``, ``0x7f.1`` and ``127.1`` as
127.0.0.1 although no parser here does, so anything but a canonical dotted quad is refused."""

ALWAYS_DENIED: Final = tuple(
    ipaddress.ip_network(n)
    for n in (
        "127.0.0.0/8",  # loopback: this server's own services
        "::1/128",  # loopback (IPv6)
        "0.0.0.0/8",  # "this network", including the unspecified address
        "::/128",  # unspecified (IPv6)
        # link-local: AWS, GCP, Azure, OpenStack and DigitalOcean metadata (169.254.169.254),
        # the AWS ECS task-role endpoint (169.254.170.2), Tencent (169.254.0.23)
        "169.254.0.0/16",
        "fe80::/10",  # link-local (IPv6)
        "224.0.0.0/4",  # multicast
        "ff00::/8",  # multicast (IPv6)
        "255.255.255.255/32",  # broadcast
        "100.100.100.200/32",  # Alibaba Cloud metadata, inside CGNAT
        "168.63.129.16/32",  # Azure wireserver and host agent (a public-looking address)
        "192.0.0.192/32",  # Oracle Cloud metadata
        "fd00:ec2::/32",  # AWS IPv6 metadata (fd00:ec2::254) and its service range, inside fc00::/7
    )
)
"""Never reachable: not publicly, not with the intranet switch. Loopback, link-local, multicast
and the cloud providers' metadata and control endpoints, including those that sit inside the
ranges the switch opens. Embedded IPv4 forms of these are refused too (:func:`address_allowed`).
The server's *own* addresses on its private interfaces are not listed: the plan does not rule
them out, so with the switch on a subscription can reach a service on this host's private
address, like any other internal host (see the setting's description)."""

# What the intranet switch adds (after ALWAYS_DENIED is applied): the private ranges.
_PRIVATE: Final = tuple(
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",  # CGNAT, less the denied /32 above
        "198.18.0.0/15",  # benchmarking: some intranets live here
        "fc00::/7",  # unique local, less fd00:ec2::/32 above
    )
)


@dataclass(frozen=True)
class Policy:
    allow_private: bool = False
    """The ``allow_private_subscription_urls`` setting."""
    may_use_private: bool = True
    """``False`` for a save by someone without ``events.manage``: the switch does not apply."""

    @property
    def intranet(self) -> bool:
        return self.allow_private and self.may_use_private


def effective(policy_setting: bool, *, may_use_private: bool) -> Policy:
    return Policy(allow_private=policy_setting, may_use_private=may_use_private)


def flag_after_save(previous: bool, *, url_changed: bool, saver_may_use_private: bool) -> bool:
    """The stored ``may_use_private`` after a save. A new or changed address takes the saver's
    right (so a non-manager editing a manager's internal subscription clears it); any other edit
    leaves it as it was and never grants it."""
    return saver_may_use_private if url_changed else previous


def user_code(error: UnsafeURLError) -> str:
    """The closed, user-facing code for a guard refusal. A private address and a host that does
    not resolve are one code, so the answer maps nothing."""
    return constants.URL_REFUSAL_CODES.get(error.code, "url_invalid")


def _invalid() -> UnsafeURLError:
    return UnsafeURLError("invalid_url")


def _valid_host(host: bytes) -> bool:
    """Every ``xn--`` label must be a real A-label (httpx only encodes, it does not decode)."""
    for label in host.decode("ascii", "replace").split("."):
        if label.lower().startswith("xn--"):
            try:
                idna.decode(label)
            except idna.IDNAError:
                return False
    return True


def normalise(raw: str) -> str:
    """The one stored and compared form of ``raw``. Raises ``UnsafeURLError("invalid_url")``."""
    text = raw.strip() if isinstance(raw, str) else ""
    if not text or len(text) > constants.SUBSCRIPTION_URL_MAX:
        raise _invalid()
    text = _WEBCAL.sub("https://", text, count=1)
    try:
        parsed = httpx.URL(text).copy_with(fragment=None)
    except (httpx.InvalidURL, TypeError, ValueError, UnicodeError):
        raise _invalid() from None  # httpx's message can quote part of the address
    if not parsed.scheme or not parsed.raw_host or not _valid_host(parsed.raw_host):
        raise _invalid()
    normal = str(parsed)
    if len(normal) > constants.SUBSCRIPTION_URL_MAX:
        raise _invalid()
    return normal


def _literal(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def address_allowed(ip: IPAddress, *, allow_private: bool) -> bool:
    """Whether a connection to ``ip`` may be made.

    First, :data:`ALWAYS_DENIED`, whatever the switch says. An IPv6 form that embeds an IPv4
    address (mapped, compatible, NAT64, 6to4, Teredo) is judged by what it embeds, and refused
    if any of it is refused. Then: publicly routable, or (with the switch) a private range.
    """
    if any(ip in net for net in ALWAYS_DENIED if net.version == ip.version):
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded and not all(
            address_allowed(v4, allow_private=allow_private) for v4 in embedded
        ):
            return False
        if embedded and allow_private:
            return True  # every embedded address passed, and the switch is on
    if is_public_address(ip):
        return True
    return allow_private and any(ip in net for net in _PRIVATE if net.version == ip.version)


def check(url: str | httpx.URL, policy: Policy) -> tuple[str, int]:
    """The syntactic half: scheme, credentials, port and the host's own spelling. Returns
    ``(host, port)``; never resolves. A literal IP is judged by :func:`address_allowed` here."""
    try:
        parsed = url if isinstance(url, httpx.URL) else httpx.URL(url.strip())
    except (httpx.InvalidURL, TypeError, ValueError, UnicodeError):
        raise _invalid() from None
    scheme = parsed.scheme.lower()
    if scheme == "http" and not policy.intranet:
        raise UnsafeURLError("invalid_scheme")
    if scheme not in _DEFAULT_PORT:
        raise UnsafeURLError("invalid_scheme")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise _invalid()
    ports = _ANY_PORT if policy.intranet else frozenset({_DEFAULT_PORT[scheme]})
    host, port = url_safety.check_url(parsed, allowed_ports=ports)
    literal = _literal(host)
    if literal is not None:
        if not address_allowed(literal, allow_private=policy.intranet):
            raise UnsafeURLError("non_public_address")
    elif _NUMERIC_HOST.match(host):
        raise _invalid()
    return host, port


def resolve_allowed(url: httpx.URL, policy: Policy) -> tuple[str, tuple[str, ...]]:
    """Resolve ``url``'s host and require **every** address to pass the guard.

    Returns ``(host, ips)``: the host as it goes in the ``Host`` header and in SNI, and each
    distinct address in resolver order, the only addresses a fetch may dial. Blocking
    (``getaddrinfo``): call it through the bounded resolver pool. Every failure raises.
    """
    host, port = check(url, policy)
    literal = _literal(host)
    if literal is not None:  # judged by check(); nothing to look up
        return host, (str(literal),)
    sock = url_safety.socket
    try:
        infos = sock.getaddrinfo(host, port, type=sock.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise UnsafeURLError("unresolvable_host") from None
    if not infos:
        raise UnsafeURLError("unresolvable_host")
    ips: list[str] = []
    for info in infos:
        ip = _parse_ip(str(info[4][0]))
        if not address_allowed(ip, allow_private=policy.intranet):
            logger.warning(
                "Blocked fetch of a non-public address",
                extra={"host": host, "resolved_ip": str(ip)},
            )
            raise UnsafeURLError("non_public_address")
        if str(ip) not in ips:
            ips.append(str(ip))
    return host, tuple(ips)
