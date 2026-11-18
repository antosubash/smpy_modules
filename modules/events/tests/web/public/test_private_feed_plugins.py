"""Plugin sources in a private feed: every enabled source, as the link's owner."""

from __future__ import annotations

from datetime import UTC, datetime

import icalendar
import pytest
from sm_events.calendar import registry
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar
from sm_events.web.endpoints.public import _private_feed
from sqlalchemy import select

from tests.support.private_feed import private_http, seed_world
from tests.support.sources import FakeSource, install, item, ok

WHEN = datetime(2026, 4, 10, 10, tzinfo=UTC)


def items(count, prefix="x"):
    return [
        item(
            f"{prefix}{i}",
            f"{prefix.upper()} {i}",
            start=WHEN.replace(hour=1 + i),
            end=WHEN.replace(hour=2 + i),
        )
        for i in range(count)
    ]


def uids(response) -> list[str]:
    return [str(c["UID"]) for c in icalendar.Calendar.from_ical(response.content).walk("VEVENT")]


@pytest.fixture
def private_source(monkeypatch):
    source = FakeSource("acme:priv", ok(*items(1, "p")), public=False)
    install(monkeypatch, source)
    yield source
    registry.reset_registry()


async def enable_on_p(world, source_ids):
    with tenant_scope(world.tenant):
        async with world.http.db_state.session_factory() as db:
            row = (
                await db.execute(select(Calendar).where(Calendar.id == world.cals["P"].id))
            ).scalar_one()
            row.sources = [{"id": i, "settings": {}} for i in source_ids]
            await db.commit()


async def test_private_feed_calls_sources_with_owner_viewer(private_source):
    async with private_http() as http:
        world = await seed_world(http)
        await enable_on_p(world, ["acme:priv"])
        got = await http.get(world.path)
        assert got.status_code == 200, got.text
        assert f"acme:priv:{world.cals['P'].id}:p0" in uids(
            got
        )  # a non-public source: the owner is signed in
        ((ctx, start, end),) = private_source.calls
        assert ctx.viewer.user_id == "sv" and ctx.viewer.roles == ("viewer",)
        assert "events.view" in ctx.viewer.permissions
        assert ctx.calendar.id == world.cals["P"].id and ctx.tenant_id == "default"
        assert (end - start).days == constants.FEED_DAYS_BACK + constants.FEED_DAYS_AHEAD
        assert (end - start).days <= constants.SOURCE_WINDOW_MAX_DAYS


async def test_private_feed_viewer_missing_skips_plugins_still_200(private_source, monkeypatch):
    async with private_http() as http:
        world = await seed_world(http)
        await enable_on_p(world, ["acme:priv"])

        async def none(*a, **k):
            return None

        monkeypatch.setattr(_private_feed, "feed_viewer", none)
        got = await http.get(world.path)
        assert got.status_code == 200 and uids(got) == [world.pub.uid]
        assert private_source.calls == []

        async def boom(*a, **k):
            raise RuntimeError("directory down")

        monkeypatch.setattr(_private_feed, "feed_viewer", boom)
        again = await http.get(world.path)
        assert again.status_code == 200 and uids(again) == [world.pub.uid]
        assert private_source.calls == []


async def test_component_cap_drops_plugin_items_first(monkeypatch):
    source = FakeSource("acme:priv", ok(*items(5)), public=False)
    install(monkeypatch, source)
    monkeypatch.setattr(constants, "FEED_MAX_COMPONENTS", 3)
    try:
        async with private_http() as http:
            world = await seed_world(http)
            await enable_on_p(world, ["acme:priv"])
            got = await http.get(world.path)
            assert got.status_code == 200
            found = uids(got)
            assert world.pub.uid in found and len(found) == 3  # own first, then two of five
            assert got.headers["x-events-truncated"] == "1"
    finally:
        registry.reset_registry()


async def test_a_failing_source_keeps_the_feed(monkeypatch):
    from tests.support.sources import raises

    install(monkeypatch, FakeSource("acme:priv", raises))
    try:
        async with private_http() as http:
            world = await seed_world(http)
            await enable_on_p(world, ["acme:priv"])
            got = await http.get(world.path)
            assert got.status_code == 200 and uids(got) == [world.pub.uid]
    finally:
        registry.reset_registry()


async def test_sources_see_the_link_owner_never_a_wider_viewer(private_source):
    """A manager's session on the request changes nothing: the viewer is the link's owner,
    rebuilt from the directory and the permission registry, as the feed's own events are."""
    from tests.support.app import as_user

    async with private_http() as http:
        world = await seed_world(http)
        await enable_on_p(world, ["acme:priv"])
        manager = as_user("m", "events.view", "events.manage", "events.publish")
        got = await http.get(world.path, headers=manager)
        assert got.status_code == 200
        ((ctx, _s, _e),) = private_source.calls
        assert ctx.viewer.user_id == "sv" and ctx.viewer.roles == ("viewer",)
        assert ctx.viewer.permissions == frozenset({"events.view"})
        assert "events.manage" not in ctx.viewer.permissions


async def test_a_refused_link_is_one_answer_and_calls_no_source(private_source, monkeypatch):
    from tests.support.private_feed import fingerprint, invented

    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    async with private_http() as http:
        world = await seed_world(http)
        await enable_on_p(world, ["acme:priv"])
        baseline = fingerprint(await http.get(world.path.replace(world.secret, invented("U"))))
        http.app.state.user_directory.roles["sv"] = ("a",)  # events.view lost
        got = await http.get(world.path)
        assert fingerprint(got) == baseline and got.status_code == 404
        assert private_source.calls == []
