"""A failed plugin answer is never cached."""

from __future__ import annotations

from tests.support.public import seed_public
from tests.support.sources import raises, sleeps
from tests.web.public.test_plugin_leaks import enable, spies, surfaces

__all__ = ["spies"]


async def test_a_failed_public_plugin_answer_is_not_cached(public_locales_client, spies):
    """A health problem must not be kept for the cache lifetime: no validator, ``no-store``."""
    fx = await seed_public(public_locales_client)
    await enable(public_locales_client, fx, pub=["acme:pub"])
    _, public = spies
    for name in ("api", "calendar_ics", "cal_ics"):
        healthy = await public_locales_client.get(surfaces(fx)[name])
        assert "etag" in healthy.headers and "no-store" not in healthy.headers["cache-control"]
    public._behave = raises
    for name in ("api", "calendar_ics", "cal_ics"):
        got = await public_locales_client.get(surfaces(fx)[name])
        assert got.status_code == 200, name
        assert got.headers["cache-control"] == "no-store", name
        assert "etag" not in got.headers, name
    from sm_events.core import constants

    constants.SOURCE_TIMEOUT_SECONDS, saved = 0.3, constants.SOURCE_TIMEOUT_SECONDS
    public._behave = sleeps(10)
    try:
        got = await public_locales_client.get(surfaces(fx)["api"])  # a timeout is a failure too
    finally:
        constants.SOURCE_TIMEOUT_SECONDS = saved
    assert got.headers["cache-control"] == "no-store"
