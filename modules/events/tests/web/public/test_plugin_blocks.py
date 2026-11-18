"""The blocks' occurrences route follows PR 6's rule for plugin sources: a public source on a public
calendar only, no viewer, a degraded answer is ``no-store``, and no event id in any item."""

from __future__ import annotations

from sm_events.core import constants

from tests.support.public import seed_public
from tests.support.sources import raises
from tests.web.public.leaks import assert_no_event_ids
from tests.web.public.test_plugin_leaks import enable, spies

__all__ = ["spies"]

URL = (
    f"{constants.PUBLIC_BLOCKS_API}/occurrences?start=2026-03-01T00:00:00Z&end=2026-06-01T00:00:00Z"
)


async def test_blocks_route_includes_public_sources_only(public_locales_client, spies):
    fx = await seed_public(public_locales_client)
    await enable(public_locales_client, fx, pub=["acme:pub", "acme:priv"])
    got = await public_locales_client.get(URL)
    assert got.status_code == 200
    assert "SPY-PUBLIC" in got.text and "SPY-PRIVATE" not in got.text
    assert_no_event_ids(
        got.text, fx
    )  # a plugin item's key carries a calendar id, never an event id


async def test_blocks_route_degraded_answer_is_not_cached(public_locales_client, spies):
    fx = await seed_public(public_locales_client)
    await enable(public_locales_client, fx, pub=["acme:pub"])
    _, public = spies
    public._behave = raises
    got = await public_locales_client.get(URL)
    assert got.status_code == 200
    assert got.headers["cache-control"] == "no-store" and "etag" not in got.headers
