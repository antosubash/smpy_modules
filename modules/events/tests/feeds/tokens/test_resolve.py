"""A token's access is derived from its owner's rights on every request, never remembered."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sharing.models import ResourceShare
from sm_events.core.access.events import visible_events
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.select import feed_events
from sm_events.feeds.tokens import service
from sm_events.feeds.tokens.codec import hash_token
from sm_events.feeds.tokens.resolve import lookup, resolve, touch_last_used
from sm_events.models import Calendar, FeedToken
from sqlalchemy import delete, event, select

from tests.support.access import principal, seed_calendars
from tests.support.calendars import seed_event
from tests.support.tokens import (
    NOW,
    fake_request,
    install_members,
    token_app,
)

V = "events.view"


class Statements:
    """Counts the statements an engine runs, for 'exactly one' and 'the same number'."""

    def __init__(self, state) -> None:
        self.count = 0
        self._engine = state.engine.sync_engine
        event.listen(self._engine, "after_cursor_execute", self._hit)

    def _hit(self, *_args) -> None:
        self.count += 1

    def reset(self) -> int:
        seen, self.count = self.count, 0
        return seen

    def close(self) -> None:
        event.remove(self._engine, "after_cursor_execute", self._hit)


@pytest.fixture
async def world():
    """Calendar ``P`` shared with ``sv`` (view), one published and one draft event, a token."""
    app, state = await token_app()
    async with state.session_factory() as db:
        cals = await seed_calendars(db)
        pub = await seed_event(db, cals["P"], title="Public", status="published", slug="pub")
        draft = await seed_event(db, cals["P"], title="Draft", status="draft", slug="draft")
        await db.commit()
    created = await _token(app, state, cals["P"], "sv")
    yield app, state, cals, created, (pub, draft)
    await state.engine.dispose()


async def _token(app, state, calendar, user, perms=(V,)):
    async with state.session_factory() as db:
        got = await service.create_token(
            db,
            fake_request(app),
            principal(user, *perms),
            calendar.id,
            label="Phone",
            locale="en",
            now=NOW,
        )
        await db.commit()
        return got


async def _resolve(app, state, secret, *, host_tenant=None):
    async with state.session_factory() as db:
        row = await lookup(db, secret)
        return await resolve(app, db, fake_request(app), row, host_tenant=host_tenant)


@pytest.mark.unbound_tenant
async def test_lookup_is_tenant_free():
    _app, state = await token_app(multi=True)
    try:
        with tenant_scope("b"):
            async with state.session_factory() as db:
                cal = Calendar(slug="x", name="X", owner_id="o")
                db.add(cal)
                await db.flush()
                db.add(
                    FeedToken(
                        calendar_id=cal.id,
                        user_id="sv",
                        token_hash=hash_token("evf_" + "C" * 43),
                        label="L",
                        locale="en",
                    )
                )
                await db.commit()
        counter = Statements(state)
        try:
            async with state.session_factory() as db:  # nothing bound
                row = await lookup(db, "evf_" + "C" * 43)
                assert row is not None
                assert (row.tenant_id, row.user_id, row.locale, row.revoked) == (
                    "b",
                    "sv",
                    "en",
                    False,
                )
                assert counter.reset() == 1  # one narrow statement, nothing else
                assert await lookup(db, "evf_" + "D" * 43) is None
                assert counter.reset() == 1
        finally:
            counter.close()
    finally:
        await state.engine.dispose()


async def test_lookup_never_reads_the_token_back(world):
    _app, state, _cals, created, _ = world
    async with state.session_factory() as db:
        row = await lookup(db, created.secret)
    assert row is not None
    assert created.secret not in repr(row)
    assert row.id == created.token.id


async def test_resolve_none_row_is_none(world):
    app, state, *_ = world
    async with state.session_factory() as db:
        assert await resolve(app, db, fake_request(app), None, host_tenant=None) is None


async def test_resolve_serves_the_owner(world):
    app, state, cals, created, _ = world
    access = await _resolve(app, state, created.secret)
    assert access is not None
    assert access.who.user_id == "sv" and access.who.has(V)
    assert access.calendar.id == cals["P"].id


async def _drop_share(state, cals, user="sv"):
    async with state.session_factory() as db:
        await db.execute(
            delete(ResourceShare.__table__).where(  # type: ignore[arg-type]
                ResourceShare.__table__.c.subject_id == user,
                ResourceShare.__table__.c.tenant_id == "default",
            )
        )
        await db.commit()


async def _set_trash(state, calendar, trashed: bool):
    async with state.session_factory() as db:
        cal = (
            await db.execute(
                select(Calendar)
                .where(Calendar.id == calendar.id)
                .execution_options(include_deleted=True)
            )
        ).scalar_one()
        cal.is_deleted = trashed
        await db.commit()


async def test_resolve_follows_access_changes(world):
    app, state, cals, created, _ = world
    secret = created.secret
    directory = app.state.user_directory

    async def served() -> bool:
        return await _resolve(app, state, secret) is not None

    assert await served()

    # The directory says the account is disabled; reactivated, the link lives again.
    email, name, _active = directory.users["sv"]
    directory.users["sv"] = (email, name, False)
    assert not await served()
    directory.users["sv"] = (email, name, True)
    assert await served()

    # The owner loses events.view (their role stops granting it), and gets it back.
    directory.roles["sv"] = ("a",)
    assert not await served()
    directory.roles["sv"] = ("viewer",)
    assert await served()

    # The identity provider stops reporting roles.
    directory.roles["sv"] = None
    assert not await served()
    directory.roles["sv"] = ("viewer",)

    # The calendar is trashed, then restored.
    await _set_trash(state, cals["P"], True)
    assert not await served()
    await _set_trash(state, cals["P"], False)
    assert await served()

    # The share is removed: the private calendar is no longer theirs to see.
    await _drop_share(state, cals)
    assert not await served()

    # Revoked: no revival.
    async with state.session_factory() as db:
        await service.revoke_token(db, principal("sv", V), created.token.id, now=NOW)
        await db.commit()
    assert not await served()


async def test_visibility_narrowed_and_widened(world):
    """An internal calendar served to any member; made private, it stops for a non-owner."""
    app, state, cals, _created, _ = world
    got = await _token(app, state, cals["I"], "x")
    assert await _resolve(app, state, got.secret) is not None
    async with state.session_factory() as db:
        cal = (await db.execute(select(Calendar).where(Calendar.id == cals["I"].id))).scalar_one()
        cal.visibility = "private"
        await db.commit()
    assert await _resolve(app, state, got.secret) is None  # x holds no share on it
    async with state.session_factory() as db:
        cal = (await db.execute(select(Calendar).where(Calendar.id == cals["I"].id))).scalar_one()
        cal.visibility = "internal"
        await db.commit()
    assert await _resolve(app, state, got.secret) is not None


@pytest.mark.unbound_tenant
async def test_a_removed_member_is_refused_then_served_again():
    app, state = await token_app(multi=True)
    members = {"a": {"sv"}}
    install_members(app, members)
    try:
        with tenant_scope("a"):
            async with state.session_factory() as db:
                cals = await seed_calendars(db)
                await db.commit()
            got = await _token(app, state, cals["P"], "sv")
            assert await _resolve(app, state, got.secret) is not None
            members["a"].discard("sv")
            assert await _resolve(app, state, got.secret) is None
            members["a"].add("sv")
            assert await _resolve(app, state, got.secret) is not None
    finally:
        await state.engine.dispose()


async def test_host_tenant_mismatch(world):
    app, state, _cals, created, _ = world
    assert await _resolve(app, state, created.secret, host_tenant="a") is None
    assert await _resolve(app, state, created.secret, host_tenant=None) is not None
    assert await _resolve(app, state, created.secret, host_tenant="default") is not None


async def test_every_refusal_with_a_row_runs_the_same_statements(world):
    """Work does not depend on why a token is refused, so the refusal says nothing about it."""
    app, state, cals, created, _ = world
    directory = app.state.user_directory
    counter = Statements(state)
    try:
        counts: dict[str, int] = {}
        counter.reset()
        assert await _resolve(app, state, created.secret) is not None
        counts["served"] = counter.reset()

        email, name, _ = directory.users["sv"]
        directory.users["sv"] = (email, name, False)
        assert await _resolve(app, state, created.secret) is None
        counts["inactive"] = counter.reset()
        directory.users["sv"] = (email, name, True)

        assert await _resolve(app, state, created.secret, host_tenant="a") is None
        counts["host"] = counter.reset()

        directory.roles["sv"] = None
        assert await _resolve(app, state, created.secret) is None
        counts["roles_unknown"] = counter.reset()
        directory.roles["sv"] = ("viewer",)

        await _drop_share(state, cals)
        counter.reset()
        assert await _resolve(app, state, created.secret) is None
        counts["share_removed"] = counter.reset()

        async with state.session_factory() as db:
            await service.revoke_token(db, principal("sv", V), created.token.id, now=NOW)
            await db.commit()
        counter.reset()
        assert await _resolve(app, state, created.secret) is None
        counts["revoked"] = counter.reset()
    finally:
        counter.close()
    refused = {k: v for k, v in counts.items() if k != "served"}
    assert len(set(refused.values())) == 1, counts


async def test_feed_is_published_only(world):
    """An owner who may write drafts still gets published events only."""
    app, state, cals, _created, (pub, draft) = world
    mine = await _token(app, state, cals["P"], "o", perms=(V, "events.edit"))
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


async def _last_used(state, token_id):
    async with state.session_factory() as db:
        db.sync_session.expire_all()
        return (
            await db.execute(select(FeedToken.last_used_at).where(FeedToken.id == token_id))
        ).scalar_one()


async def test_touch_coarse(world):
    _app, state, _cals, created, _ = world
    async with state.session_factory() as db:
        row = await lookup(db, created.secret)
    assert row is not None
    first = NOW
    await touch_last_used(state.session_factory, row, now=first)
    assert await _last_used(state, row.id) == first
    await touch_last_used(state.session_factory, row, now=first + timedelta(minutes=59))
    assert await _last_used(state, row.id) == first  # within the hour: no write
    later = first + timedelta(hours=1, minutes=1)
    await touch_last_used(state.session_factory, row, now=later)
    assert await _last_used(state, row.id) == later


async def test_touch_swallows_and_logs_the_class(world, caplog):
    _app, state, _cals, created, _ = world
    async with state.session_factory() as db:
        row = await lookup(db, created.secret)

    def broken():
        raise ConnectionError(f"down: {created.secret}")

    with caplog.at_level("DEBUG"):
        await touch_last_used(broken, row, now=NOW)  # must not raise
    assert "ConnectionError" in caplog.text
    assert created.secret not in caplog.text
    assert datetime(2000, 1, 1, tzinfo=UTC) < NOW
