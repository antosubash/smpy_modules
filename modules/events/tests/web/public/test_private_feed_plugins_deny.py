"""With a plugin source enabled on the calendar, a private link still says "no" in one way, and a
failing plugin changes neither a valid link's answer nor a refusal."""

from __future__ import annotations

import pytest
from sm_events.calendar import registry
from sm_events.core import constants

from tests.support.private_feed import (
    MEMBERS,
    feed_path,
    fingerprint,
    invented,
    private_http,
    seed_world,
)
from tests.support.sources import FakeSource, install, ok, raises
from tests.web.public.test_private_feed_leaks import CASES, _break
from tests.web.public.test_private_feed_plugins import enable_on_p, items, uids

pytestmark = pytest.mark.unbound_tenant


@pytest.fixture(params=["working", "failing"])
async def matrix(request, monkeypatch):
    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    source = FakeSource("acme:priv", ok(*items(2, "p")) if request.param == "working" else raises)
    install(monkeypatch, source)
    members = {k: set(v) for k, v in MEMBERS.items()}
    async with private_http(members=members) as http:
        world = await seed_world(http)
        await enable_on_p(world, ["acme:priv"])
        yield http, world, members, source
    registry.reset_registry()


@pytest.mark.parametrize("case", [c for c in CASES if c != "not_member"])
async def test_every_refusal_is_the_one_refusal_with_a_source_enabled(matrix, case):
    http, world, members, source = matrix
    baseline = fingerprint(await http.get(feed_path(invented("U"))))
    assert baseline[0] == 404 and baseline[1] == constants.PRIVATE_FEED_ERROR_BODY
    if case == "malformed":
        got = await http.get(feed_path("not-a-token"))
    elif case == "unknown":
        got = await http.get(feed_path(invented("V")))
    else:
        headers = await _break(http, world, case, members)
        got = await http.get(world.path, headers=headers)
    assert fingerprint(got) == baseline, case
    assert source.calls == [], "a refused link must not call a plugin"


async def test_a_valid_link_is_served_whether_or_not_the_plugin_works(matrix):
    http, world, _members, source = matrix
    got = await http.get(world.path)
    assert got.status_code == 200, got.text
    found = uids(got)
    assert world.pub.uid in found and world.draft.uid not in found
    assert len(source.calls) == 1
    if source._behave is raises:  # a failing source adds nothing and refuses nothing
        assert found == [world.pub.uid]
    else:
        assert len(found) == 3
