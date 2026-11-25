"""Hydration adopts the server's head instead of doubling it (#461).

Inertia's head manager only de-duplicates elements carrying ``data-inertia``; the React side sets
the same key through ``head-key`` in ``PublicHead.tsx``. A server tag without the marker is
invisible to the manager and hydration adds a second copy; a keyed server tag the client does not
render is deleted on hydration. So the two key sets must be the same, and no key may repeat.
"""

from __future__ import annotations

import re
from pathlib import Path

from sm_events.web.endpoints.public import _head

from tests.web.public.test_index_pages import fx  # noqa: F401  (fixture)

PUBLIC_HEAD = Path(__file__).resolve().parents[3] / "sm_events" / "ui" / "public" / "PublicHead.tsx"
SOURCE = PUBLIC_HEAD.read_text(encoding="utf-8")
ALTERNATES = [
    {"locale": "en", "url": "https://x.example/e"},
    {"locale": "de", "url": "https://x.example/de/e"},
    {"locale": "x-default", "url": "https://x.example/e"},
]


def _client_keys(*, event: bool) -> set[str]:
    """The keys ``PublicHead`` renders. ``event`` is the event page (it also renders twitter:*);
    the dynamic ``hreflang-${locale}`` key is expanded for ``ALTERNATES``."""
    keys: set[str] = set()
    for key in re.findall(r'head-key="([^"]+)"', SOURCE):
        keys.add(key)
    for _ in re.findall(r"head-key=\{`hreflang-\$\{a\.locale\}`\}", SOURCE):
        keys.update(f"hreflang-{a['locale']}" for a in ALTERNATES)
    if not event:
        keys -= {"twitter:card", "twitter:image"}
    return keys


def _server_keys(head: str) -> list[str]:
    return re.findall(r'data-inertia="([^"]+)"', head)


def _event_head() -> str:
    return _head.event_head(
        title="T", description="d", canonical="https://x.example/e", image="https://x.example/i.png",
        index_in_search=False, json_ld={"@type": "Event"}, locale="en", alternates=ALTERNATES,
        nonce="n",
    )  # fmt: skip


def _listing_head() -> str:
    return _head.listing_head(
        title="T", description="d", canonical="https://x.example/", feed_url="/events/calendar.ics",
        locale="en", alternates=ALTERNATES, robots="noindex,follow",
    )  # fmt: skip


def test_event_head_keys_match_the_client():
    keys = _server_keys(_event_head())
    assert len(keys) == len(set(keys)), "a key appears twice in the head"
    assert set(keys) == _client_keys(event=True) - {"feed"}


def test_listing_head_keys_match_the_client():
    keys = _server_keys(_listing_head())
    assert len(keys) == len(set(keys)), "a key appears twice in the head"
    # The listing has no image and no JSON-LD, so the client renders neither there.
    assert set(keys) == _client_keys(event=False) - {"og:image", "json-ld"}


def test_json_ld_keeps_its_nonce_beside_the_key():
    assert '<script type="application/ld+json" data-inertia="json-ld" nonce="n">' in _event_head()


def test_the_title_is_unkeyed_so_the_client_replaces_it():
    # Inertia removes every unmanaged <title> once the client renders one: one title remains.
    assert "<title>T</title>" in _event_head() and "<title data-inertia" not in _event_head()


async def test_served_pages_carry_the_keys(public_locales_client, fx):  # noqa: F811
    for path, event in ((f"/events/{fx.slug(fx.one_off)}", True), ("/events/", False)):
        head = (await public_locales_client.get(path)).text.split("</head>", 1)[0]
        keys = _server_keys(head)
        assert len(keys) == len(set(keys)), path
        hreflang = {"hreflang-en", "hreflang-de", "hreflang-x-default"}
        assert set(keys) <= _client_keys(event=event) | hreflang
        assert "canonical" in keys and "og:title" in keys
        assert ('data-inertia="twitter:card"' in head) is event
