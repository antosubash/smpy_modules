"""Who may still be reminded, decided at send time and failing closed on every doubt."""

from __future__ import annotations

import logging
import uuid

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Visibility
from sm_events.reminders import recipients
from sm_events.reminders.runtime import Recipient, web_runtime

from tests.reminders.support import drop_share, published, world
from tests.support.app import Directory, build_app
from tests.support.calendars import seed_event
from tests.support.tokens import ROLES, USERS, install_members

TENANT = "t1"


@pytest.fixture
async def single():
    app, state = await build_app()
    app.state.user_directory = Directory(dict(USERS), dict(ROLES))
    async with state.session_factory() as db:
        yield app, db
    await state.engine.dispose()


async def _cast(db):
    cals = await world(db)
    return cals, {k: await published(db, c, title=f"E{k}") for k, c in cals.items()}


async def _ask(app, db, wanted, tenant="default"):
    return await recipients.eligible(db, web_runtime(app), tenant_id=tenant, wanted=wanted)


def _ids(found, user):
    return found.allowed[user][1] if user in found.allowed else None


async def test_everyone_who_may_see_it(single):
    app, db = single
    _, ev = await _cast(db)
    wanted = {u: {ev["U"].id, ev["I"].id, ev["P"].id} for u in ("v", "sv", "o", "m", "x")}
    found = await _ask(app, db, wanted)
    assert found.denied == {}
    assert _ids(found, "v") == {ev["U"].id, ev["I"].id}  # not the private calendar
    assert _ids(found, "sv") == {ev["U"].id, ev["I"].id, ev["P"].id}  # a view share
    assert _ids(found, "o") == {ev["U"].id, ev["I"].id, ev["P"].id}  # the owner
    assert _ids(found, "m") == {ev["U"].id, ev["I"].id, ev["P"].id}  # a manager sees private
    recipient = found.allowed["v"][0]
    assert isinstance(recipient, Recipient)
    assert (recipient.user_id, recipient.email) == ("v", "v@example.com")
    assert recipient.principal.user_id == "v"


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("unknown", "not_resolvable"),
        ("inactive", "not_resolvable"),
        ("roles_unknown", "not_resolvable"),
        ("no_email", "no_email"),
        ("email_with_a_newline", "no_email"),
        ("unverified", "unverified_email"),
        ("no_view", "no_view"),
    ],
)
async def test_recipients_fail_closed(single, case, reason):
    app, db = single
    _, ev = await _cast(db)
    directory: Directory = app.state.user_directory
    user = "v"
    if case == "unknown":
        user = "ghost"
    elif case == "inactive":
        directory.users["v"] = ("v@example.com", "V", False)
    elif case == "roles_unknown":
        directory.roles["v"] = None
    elif case == "no_email":
        directory.users["v"] = ("", "V", True)
    elif case == "email_with_a_newline":
        directory.users["v"] = ("v@example.com\nBcc: x@y", "V", True)
    elif case == "unverified":
        directory.verified["v"] = False
    elif case == "no_view":
        user = "a"  # active, member, but no role grants events.view
    found = await _ask(app, db, {user: {ev["U"].id}})
    assert found.allowed == {}
    assert found.denied == {reason: 1}


async def test_an_unreported_verification_passes_and_a_verified_one_too(single):
    app, db = single
    _, ev = await _cast(db)
    directory: Directory = app.state.user_directory
    directory.verified.update({"sv": True, "v": None})  # None: the directory does not say
    found = await _ask(app, db, {"sv": {ev["U"].id}, "v": {ev["U"].id}})
    assert set(found.allowed) == {"sv", "v"}


async def test_one_bad_user_does_not_spoil_the_others(single):
    app, db = single
    _, ev = await _cast(db)
    found = await _ask(app, db, {"v": {ev["U"].id}, "ghost": {ev["U"].id}, "a": {ev["U"].id}})
    assert set(found.allowed) == {"v"}
    assert found.denied == {"not_resolvable": 1, "no_view": 1}


async def test_a_share_removed_hides_only_that_event(single):
    app, db = single
    cals, ev = await _cast(db)
    wanted = {"sv": {ev["P"].id, ev["U"].id}}
    assert _ids(await _ask(app, db, wanted), "sv") == {ev["P"].id, ev["U"].id}
    await drop_share(db, cals["P"], "sv")
    found = await _ask(app, db, wanted)
    assert _ids(found, "sv") == {ev["U"].id}
    assert found.denied == {}  # still a recipient; only the private event is gone


async def test_a_user_left_with_nothing_is_denied_not_empty(single):
    app, db = single
    cals, ev = await _cast(db)
    await drop_share(db, cals["P"], "sv")
    found = await _ask(app, db, {"sv": {ev["P"].id}})
    assert found.allowed == {}
    assert found.denied == {"not_visible": 1}


async def test_internal_to_private_hides_it_from_a_non_owner(single):
    app, db = single
    cals, ev = await _cast(db)
    wanted = {"v": {ev["I"].id}, "o": {ev["I"].id}}
    assert set((await _ask(app, db, wanted)).allowed) == {"v", "o"}
    cals["I"].visibility = Visibility.PRIVATE.value
    await db.flush()
    found = await _ask(app, db, wanted)
    assert set(found.allowed) == {"o"}
    assert found.denied == {"not_visible": 1}


async def test_visible_only_published(single):
    app, db = single
    cals, ev = await _cast(db)
    draft = await seed_event(db, cals["P"], status="draft", title="Draft")
    review = await seed_event(db, cals["U"], status="in_review", title="Review")
    wanted = {u: {draft.id, review.id, ev["U"].id} for u in ("o", "se", "m")}  # writers, manager
    found = await _ask(app, db, wanted)
    for user in ("o", "se", "m"):
        assert _ids(found, user) == {ev["U"].id}, user


async def test_an_unknown_event_id_is_dropped(single):
    app, db = single
    _, ev = await _cast(db)
    found = await _ask(app, db, {"v": {uuid.uuid4(), ev["U"].id}})
    assert _ids(found, "v") == {ev["U"].id}


async def test_nothing_wanted_asks_nothing(single):
    app, db = single
    directory: Directory = app.state.user_directory
    found = await _ask(app, db, {})
    assert (found.allowed, found.denied, directory.get_many_calls) == ({}, {}, 0)


async def test_resolver_raises_denies_tenant(single, caplog):
    app, db = single
    _, ev = await _cast(db)

    class Broken(Directory):
        async def get_many(self, db, ids, *, with_roles=False):
            raise RuntimeError("secret@leak.example is down")

    app.state.user_directory = Broken(dict(USERS), dict(ROLES))
    with caplog.at_level(logging.DEBUG):
        found = await _ask(app, db, {"v": {ev["U"].id}, "sv": {ev["U"].id}})
    assert found.allowed == {} and found.denied == {"resolver_error": 2}
    text = " ".join(f"{r.getMessage()} {r.args}" for r in caplog.records)
    assert "RuntimeError" in text and "leak.example" not in text and "v@example.com" not in text


async def test_batch_one_directory_call(single):
    app, db = single
    _, ev = await _cast(db)
    users = {f"u{i}": (f"u{i}@example.com", f"U{i}", True) for i in range(50)}
    app.state.user_directory = Directory(users, dict.fromkeys(users, ("viewer",)))
    found = await _ask(app, db, {u: {ev["U"].id} for u in users})
    assert len(found.allowed) == 50
    assert app.state.user_directory.get_many_calls == 1


async def test_the_log_names_no_one(single, caplog):
    app, db = single
    _, ev = await _cast(db)
    with caplog.at_level(logging.DEBUG):
        await _ask(app, db, {"v": {ev["U"].id}, "ghost": {ev["U"].id}, "a": {ev["U"].id}})
    text = " ".join(f"{r.getMessage()} {r.args}" for r in caplog.records)
    assert "@example.com" not in text


@pytest.fixture
async def multi():
    app, state = await build_app(multi=True)
    app.state.user_directory = Directory(dict(USERS), dict(ROLES))
    yield app, state
    await state.engine.dispose()


async def _multi_cast(state):
    with tenant_scope(TENANT):
        async with state.session_factory() as db:
            _, ev = await _cast(db)
            await db.commit()
            return {k: e.id for k, e in ev.items()}


async def _multi_ask(app, state, wanted):
    with tenant_scope(TENANT):
        async with state.session_factory() as db:
            return await _ask(app, db, wanted, tenant=TENANT)


@pytest.mark.unbound_tenant
async def test_multi_members_only(multi):
    app, state = multi
    ids = await _multi_cast(state)
    install_members(app, {TENANT: {"v"}})
    found = await _multi_ask(app, state, {"v": {ids["U"]}, "sv": {ids["U"]}})
    assert set(found.allowed) == {"v"}
    assert found.denied == {"not_resolvable": 1}


@pytest.mark.unbound_tenant
async def test_multi_without_a_membership_store_is_nobody(multi):
    app, state = multi
    ids = await _multi_cast(state)
    found = await _multi_ask(app, state, {"v": {ids["U"]}})
    assert found.allowed == {} and found.denied == {"not_resolvable": 1}


@pytest.mark.unbound_tenant
async def test_multi_membership_of_another_tenant_is_not_this_one(multi):
    app, state = multi
    ids = await _multi_cast(state)
    install_members(app, {"elsewhere": {"v"}})
    found = await _multi_ask(app, state, {"v": {ids["U"]}})
    assert found.allowed == {}
