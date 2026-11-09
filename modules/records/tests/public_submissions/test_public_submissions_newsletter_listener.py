"""A failing ``SubscriptionChanged`` listener never breaks the anonymous
unsubscribe (#101): the answer is records' usual one and the opt-out is stored.

Here rather than in newsletter's suite because the submissions harness is in
records' ``tests`` package. The first test holds for any listener; the second
wires newsletter's own mirror (when installed) with a database that fails.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from sm_records.contracts.events import SubscriptionChanged

from tests.support.newsletter_http import follow, links_in, signup, subscriber


async def _signed_up(site) -> str:
    """A pending subscriber; its unsubscribe token."""
    assert (await signup(site)).status_code == 202
    return links_in(site.outbox.sent[-1])["unsubscribe"]["t"]


async def test_a_raising_listener_leaves_the_unsubscribe_intact(newsletter):
    calls: list = []

    async def broken(event):
        calls.append(event)
        raise RuntimeError("listener down")

    token = await _signed_up(newsletter)
    newsletter.app.state.sm.event_bus.subscribe(SubscriptionChanged, broken)
    resp = await follow(newsletter, "unsubscribe", token)
    assert (resp.status_code, resp.json()) == (200, {"status": "unsubscribed"})
    assert (await subscriber(newsletter))["data"]["sm_status"] == "unsubscribed"
    assert [(e.status_before, e.status_after) for e in calls] == [("pending", "unsubscribed")]


async def test_newsletters_mirror_with_a_failing_database(newsletter, caplog):
    mirror = pytest.importorskip("sm_newsletter.core.suppression.mirror")

    class _Broken:
        @property
        def session_factory(self):
            raise RuntimeError("no database")

    token = await _signed_up(newsletter)
    bus = newsletter.app.state.sm.event_bus
    mirror.subscribe(bus, SimpleNamespace(state=SimpleNamespace(sm=SimpleNamespace(db=_Broken()))))
    with caplog.at_level(logging.WARNING):
        resp = await follow(newsletter, "unsubscribe", token)
    assert (resp.status_code, resp.json()) == (200, {"status": "unsubscribed"})
    assert (await subscriber(newsletter))["data"]["sm_status"] == "unsubscribed"
    mine = [r for r in caplog.records if r.name.startswith("sm_newsletter")]
    assert [r.levelno for r in mine] == [logging.WARNING]
    assert mine[0].exc_info is not None
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
