"""A token's access is derived from its owner's rights on every request, never remembered."""

from __future__ import annotations

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.tokens import service
from sm_events.feeds.tokens.codec import hash_token
from sm_events.feeds.tokens.resolve import lookup, resolve
from sm_events.models import Calendar, FeedToken
from sqlalchemy import select

from tests.feeds.tokens.resolve_support import (
    Statements,
    V,
    drop_share,
    mint,
    resolve_for,
    set_trash,
)
from tests.support.access import principal, seed_calendars
from tests.support.tokens import NOW, fake_request, install_members, token_app


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
    access = await resolve_for(app, state, created.secret)
    assert access is not None
    assert access.who.user_id == "sv" and access.who.has(V)
    assert access.calendar.id == cals["P"].id


async def test_resolve_follows_access_changes(world):
    app, state, cals, created, _ = world
    secret = created.secret
    directory = app.state.user_directory

    async def served() -> bool:
        return await resolve_for(app, state, secret) is not None

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
    await set_trash(state, cals["P"], True)
    assert not await served()
    await set_trash(state, cals["P"], False)
    assert await served()

    # The share is removed: the private calendar is no longer theirs to see.
    await drop_share(state, cals)
    assert not await served()

    # Revoked: no revival.
    async with state.session_factory() as db:
        await service.revoke_token(db, principal("sv", V), created.token.id, now=NOW)
        await db.commit()
    assert not await served()


async def test_visibility_narrowed_and_widened(world):
    """An internal calendar served to any member; made private, it stops for a non-owner."""
    app, state, cals, _created, _ = world
    got = await mint(app, state, cals["I"], "x")
    assert await resolve_for(app, state, got.secret) is not None
    async with state.session_factory() as db:
        cal = (await db.execute(select(Calendar).where(Calendar.id == cals["I"].id))).scalar_one()
        cal.visibility = "private"
        await db.commit()
    assert await resolve_for(app, state, got.secret) is None  # x holds no share on it
    async with state.session_factory() as db:
        cal = (await db.execute(select(Calendar).where(Calendar.id == cals["I"].id))).scalar_one()
        cal.visibility = "internal"
        await db.commit()
    assert await resolve_for(app, state, got.secret) is not None


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
            got = await mint(app, state, cals["P"], "sv")
            assert await resolve_for(app, state, got.secret) is not None
            members["a"].discard("sv")
            assert await resolve_for(app, state, got.secret) is None
            members["a"].add("sv")
            assert await resolve_for(app, state, got.secret) is not None
    finally:
        await state.engine.dispose()


async def test_host_tenant_mismatch(world):
    app, state, _cals, created, _ = world
    assert await resolve_for(app, state, created.secret, host_tenant="a") is None
    assert await resolve_for(app, state, created.secret, host_tenant=None) is not None
    assert await resolve_for(app, state, created.secret, host_tenant="default") is not None
