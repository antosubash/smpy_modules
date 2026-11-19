"""Creating, listing and revoking private feed links."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sm_events.core.errors import (
    Forbidden,
    NotFound,
    PrivateFeedsUnavailable,
    TokenLimit,
    UnknownLocale,
)
from sm_events.feeds.tokens import service
from sm_events.feeds.tokens.codec import hash_token
from sm_events.models import Calendar, FeedToken
from sqlalchemy import select

from tests.support.access import principal, seed_calendars
from tests.support.tokens import NOW, fake_request, install_directory, token_app

V, E, M = "events.view", "events.edit", "events.manage"


@pytest.fixture
async def world():
    app, state = await token_app()
    async with state.session_factory() as db:
        cals = await seed_calendars(db)
        await db.commit()
    yield app, state, cals
    await state.engine.dispose()


async def _create(app, state, who, calendar, *, label="Phone", locale=None, request=None):
    async with state.session_factory() as db:
        got = await service.create_token(
            db,
            request or fake_request(app),
            who,
            calendar.id,
            label=label,
            locale=locale,
            now=NOW,
        )
        await db.commit()
        return got


async def test_create_returns_secret_once(world):
    app, state, cals = world
    got = await _create(app, state, principal("sv", V), cals["P"])
    assert got.secret.startswith("evf_")
    assert got.token.token_hash == hash_token(got.secret)
    async with state.session_factory() as db:
        row = (await db.execute(select(FeedToken))).scalar_one()
    for value in row.__dict__.values():  # nothing stored equals, or contains, the secret
        assert got.secret not in str(value)
    assert (row.user_id, row.calendar_id, row.label, row.locale) == (
        "sv",
        cals["P"].id,
        "Phone",
        "en",
    )
    assert row.created_at == NOW and row.revoked_at is None and row.last_used_at is None


async def test_create_needs_view(world):
    app, state, cals = world
    with pytest.raises(NotFound):  # sees nothing private that is not theirs or shared
        await _create(app, state, principal("v", V), cals["P"])
    with pytest.raises(NotFound):  # no events.view at all
        await _create(app, state, principal("a"), cals["P"])
    with pytest.raises(NotFound):  # anonymous
        await _create(app, state, principal(None), cals["U"])
    assert (await _create(app, state, principal("sv", V), cals["P"])).secret
    assert (await _create(app, state, principal("v", V), cals["I"])).secret  # internal: any member


async def test_create_in_a_trashed_calendar_is_not_found(world):
    app, state, cals = world
    async with state.session_factory() as db:
        cal = (await db.execute(select(Calendar).where(Calendar.id == cals["P"].id))).scalar_one()
        cal.is_deleted = True
        await db.commit()
    with pytest.raises(NotFound):
        await _create(app, state, principal("sv", V), cals["P"])


async def test_limit_five_active(world):
    app, state, cals = world
    who = principal("sv", V)
    made = [await _create(app, state, who, cals["P"], label=f"d{i}") for i in range(5)]
    with pytest.raises(TokenLimit):
        await _create(app, state, who, cals["P"])
    await _create(app, state, who, cals["I"])  # another calendar: its own budget
    await _create(app, state, principal("se", V), cals["P"])  # another user: their own
    async with state.session_factory() as db:
        await service.revoke_token(db, who, made[0].token.id, now=NOW)
        await db.commit()
    await _create(app, state, who, cals["P"])  # a revoked one no longer counts


async def test_label_and_locale():
    app, state = await token_app(settings={"content_locales": ("en", "de")})
    try:
        async with state.session_factory() as db:
            cals = await seed_calendars(db)
            await db.commit()
        who = principal("sv", V)
        with pytest.raises(UnknownLocale):
            await _create(app, state, who, cals["P"], locale="fr")
        assert (await _create(app, state, who, cals["P"])).token.locale == "en"
        assert (await _create(app, state, who, cals["P"], locale="de")).token.locale == "de"
        console_de = fake_request(app, locale="de")
        assert (await _create(app, state, who, cals["P"], request=console_de)).token.locale == "de"
        console_fr = fake_request(app, locale="fr")  # not a content locale: the default
        assert (await _create(app, state, who, cals["P"], request=console_fr)).token.locale == "en"
    finally:
        await state.engine.dispose()


async def test_unavailable_without_roles(world):
    app, state, cals = world
    install_directory(app, roles={"sv": None})
    with pytest.raises(PrivateFeedsUnavailable):
        await _create(app, state, principal("sv", V), cals["P"])
    async with state.session_factory() as db:
        assert (await db.execute(select(FeedToken))).scalars().all() == []


async def test_unavailable_for_an_unknown_account(world):
    app, state, cals = world
    with pytest.raises(PrivateFeedsUnavailable):
        await _create(app, state, principal("ghost", V), cals["I"])


async def test_a_hash_collision_is_retried(world, monkeypatch):
    """The savepoint turns the unique violation into a retry, never a 500."""
    app, state, cals = world
    first = await _create(app, state, principal("sv", V), cals["P"])
    handed = []
    queue = [first.secret, "evf_" + "B" * 43]  # the taken one, then a new one

    def next_token() -> str:
        handed.append(queue[len(handed)])
        return handed[-1]

    monkeypatch.setattr(service, "new_token", next_token)
    got = await _create(app, state, principal("se", V), cals["P"])
    assert handed == queue  # the first attempt collided and was retried
    assert got.secret == "evf_" + "B" * 43


async def test_list_own_vs_everyone(world):
    app, state, cals = world
    await _create(app, state, principal("sv", V), cals["P"], label="mine")
    await _create(app, state, principal("se", V), cals["P"], label="theirs")
    async with state.session_factory() as db:
        own = await service.list_tokens(db, principal("sv", V), cals["P"].id, everyone=False)
        assert [t.label for t in own] == ["mine"]
        with pytest.raises(Forbidden):
            await service.list_tokens(db, principal("sv", V), cals["P"].id, everyone=True)
        everyone = await service.list_tokens(db, principal("m", V, M), cals["P"].id, everyone=True)
        assert {t.label for t in everyone} == {"mine", "theirs"}
        with pytest.raises(NotFound):  # a calendar the caller cannot see
            await service.list_tokens(db, principal("v", V), cals["P"].id, everyone=False)


async def test_list_hides_revoked(world):
    app, state, cals = world
    who = principal("sv", V)
    gone = await _create(app, state, who, cals["P"], label="gone")
    await _create(app, state, who, cals["P"], label="kept")
    async with state.session_factory() as db:
        await service.revoke_token(db, who, gone.token.id, now=NOW)
        await db.commit()
        assert [
            t.label for t in await service.list_tokens(db, who, cals["P"].id, everyone=False)
        ] == ["kept"]


async def test_revoke_rules(world):
    app, state, cals = world
    made = await _create(app, state, principal("sv", V), cals["P"])
    other = await _create(app, state, principal("se", V), cals["P"])
    async with state.session_factory() as db:
        with pytest.raises(NotFound):  # someone else's token, as if it did not exist
            await service.revoke_token(db, principal("se", V), made.token.id, now=NOW)
        with pytest.raises(NotFound):
            await service.revoke_token(db, principal("m", V), made.token.id, now=NOW)  # no manage
        with pytest.raises(NotFound):  # missing: the same answer
            await service.revoke_token(db, principal("sv", V), uuid.uuid4(), now=NOW)
        await service.revoke_token(db, principal("sv", V), made.token.id, now=NOW)  # own
        await service.revoke_token(db, principal("m", V, M), other.token.id, now=NOW)  # manager
        await db.commit()
        later = NOW + timedelta(days=1)
        await service.revoke_token(db, principal("sv", V), made.token.id, now=later)  # a no-op
        await db.commit()
        rows = {t.id: t for t in (await db.execute(select(FeedToken))).scalars()}
    assert rows[made.token.id].revoked_at == NOW  # the second revoke did not move it
    assert rows[other.token.id].revoked_at == NOW


async def test_revoke_own_after_losing_the_calendar(world):
    """Losing access must never stop someone retiring their own link."""
    app, state, cals = world
    made = await _create(app, state, principal("sv", V), cals["P"])
    async with state.session_factory() as db:
        await service.revoke_token(db, principal("sv"), made.token.id, now=NOW)
        await db.commit()
        row = (await db.execute(select(FeedToken))).scalar_one()
    assert row.revoked_at == NOW
