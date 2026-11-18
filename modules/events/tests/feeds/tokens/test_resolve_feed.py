"""What a served link reads, and that a refusal does the same work whatever its reason."""

from __future__ import annotations

from sm_events.core.access.events import visible_events
from sm_events.feeds.select import feed_events
from sm_events.feeds.tokens import service
from sm_events.feeds.tokens.resolve import lookup, resolve

from tests.feeds.tokens.resolve_support import (
    Statements,
    V,
    drop_share,
    mint,
    resolve_for,
)
from tests.support.access import principal
from tests.support.tokens import NOW, fake_request


async def test_every_refusal_with_a_row_runs_the_same_statements(world):
    """Work does not depend on why a token is refused, so the refusal says nothing about it."""
    app, state, cals, created, _ = world
    directory = app.state.user_directory
    counter = Statements(state)
    try:
        counts: dict[str, int] = {}
        counter.reset()
        assert await resolve_for(app, state, created.secret) is not None
        counts["served"] = counter.reset()

        email, name, _ = directory.users["sv"]
        directory.users["sv"] = (email, name, False)
        assert await resolve_for(app, state, created.secret) is None
        counts["inactive"] = counter.reset()
        directory.users["sv"] = (email, name, True)

        assert await resolve_for(app, state, created.secret, host_tenant="a") is None
        counts["host"] = counter.reset()

        directory.roles["sv"] = None
        assert await resolve_for(app, state, created.secret) is None
        counts["roles_unknown"] = counter.reset()
        directory.roles["sv"] = ("viewer",)

        await drop_share(state, cals)
        counter.reset()
        assert await resolve_for(app, state, created.secret) is None
        counts["share_removed"] = counter.reset()

        async with state.session_factory() as db:
            await service.revoke_token(db, principal("sv", V), created.token.id, now=NOW)
            await db.commit()
        counter.reset()
        assert await resolve_for(app, state, created.secret) is None
        counts["revoked"] = counter.reset()
    finally:
        counter.close()
    refused = {k: v for k, v in counts.items() if k != "served"}
    assert len(set(refused.values())) == 1, counts


async def test_feed_is_published_only(world):
    """An owner who may write drafts still gets published events only."""
    app, state, cals, _created, (pub, draft) = world
    mine = await mint(app, state, cals["P"], "o", perms=(V, "events.edit"))
    async with state.session_factory() as db:
        row = await lookup(db, mine.secret)
        access = await resolve(app, db, fake_request(app), row, host_tenant=None)
        assert access is not None and access.who.has("events.edit")
        # The console shows this owner their drafts, so the feed's narrowing is real.
        console = (await db.execute(visible_events(access.who, include_unpublished=True))).scalars()
        assert {e.id for e in console} >= {pub.id, draft.id}
        read = await feed_events(
            db,
            calendar_id=access.row.calendar_id,
            locale="en",
            default_locale="en",
            now=NOW,
            url_for=lambda slug, loc: f"https://x/{slug}",
            events=access.events(),
        )
    assert {i.event.id for i in read.items} == {pub.id}


async def test_feed_select_is_bound_to_the_tenant_even_when_built_without_it(world):
    app, state, cals, created, _ = world
    async with state.session_factory() as db:
        row = await lookup(db, created.secret)
        access = await resolve(app, db, fake_request(app), row, host_tenant=None)
        assert access is not None
        read = await feed_events(
            db,
            calendar_id=None,
            locale="en",
            default_locale="en",
            now=NOW,
            url_for=lambda slug, loc: slug,
            events=visible_events(access.who, include_unpublished=False),
        )
    assert {i.event.calendar_id for i in read.items} == {cals["P"].id}
