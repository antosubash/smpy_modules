"""The SSRF guard and the pinned transport's hardening, and how their copies may differ.

Split out of ``parity_families.py``, which appends these to ``FAMILIES``; the rules there apply
here: an allowance is a decision, and says why.

images, ai and events each fetch a URL somebody else supplied, so each keeps the same address
rules (a published module must not import a sibling): what counts as a public address, which
IPv6 forms embed an IPv4 one. images and events also keep the guard's entry points and the
``netsafe`` wrapper that closes the socket of a cancelled TLS handshake.
"""

from __future__ import annotations

from parity_support import Copy, Family

AI = "modules/ai/sm_ai"
IMAGES_GUARD = "modules/images/sm_images/ingest/imports/url_safety.py"
EVENTS_GUARD = "modules/events/sm_events/feeds/subscriptions/url_safety.py"

SSRF_FAMILIES: tuple[Family, ...] = (
    Family(
        "SSRF address guard",
        (
            Copy(IMAGES_GUARD),
            Copy(EVENTS_GUARD),
            Copy(f"{AI}/core/url_safety.py", {"httpx2": "httpx"}),
        ),
        # The address rules are the guard; `check_url` and `resolve_public`
        # are allowed to differ below.
        shared=(
            "IPAddress",
            "ALLOWED_SCHEMES",
            "_DEFAULT_PORTS",
            "_BLOCKED_NETWORKS",
            "ALWAYS_DENIED",
            "_NAT64",
            "_V4_COMPATIBLE",
            "UnsafeURLError",
            "UnsafeURLError.__init__",
            "_embedded_ipv4",
            "is_public_address",
            "_parse_ip",
        ),
        differ={
            "check_url": "A provider endpoint may listen on any port (vLLM on 8000), so ai's "
            "copy has no port allow-list; images fetches arbitrary URLs and keeps 80/443. "
            "Events' copy equals images' (the next family pins that); its own https-only and "
            "intranet rules are in feeds/subscriptions/policy.py.",
            "resolve_public": "See check_url: images passes its port allow-list through.",
        },
    ),
    Family(
        "pinned transport hardening",
        (
            Copy("modules/images/sm_images/ingest/imports/netsafe.py"),
            Copy("modules/events/sm_events/feeds/subscriptions/netsafe.py"),
        ),
        # The whole file is the copy: it closes the socket of a cancelled TLS handshake.
        shared=None,
    ),
    Family(
        "SSRF address guard: entry points",
        (
            Copy(IMAGES_GUARD),
            Copy(EVENTS_GUARD),
        ),
        # The two copies that keep the port allow-list: `check_url` and `resolve_public` are
        # the guard's entry points, and events' copy must not wander from images'.
        shared=("DEFAULT_ALLOWED_PORTS", "check_url", "resolve_public"),
    ),
)
