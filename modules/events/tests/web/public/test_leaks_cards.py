"""The leak harness for ``contracts.cards``: a card is an anonymous surface like any other.

The same cast as the HTTP surfaces (:func:`~tests.support.calendars.seed_public_fixture`, in
both languages): no hidden event comes back by id, by any title it has, or in a search that
matches every title; another tenant's events never come back, and nothing in a card names an
owner, a revision, a status or another event.
"""

from __future__ import annotations

import pytest
from simple_module_db import like_contains_pattern
from sm_events.contracts import cards as contract
from sm_events.core.tenancy import tenant_scope

from tests.support.calendars import PublicFixture
from tests.support.public import seed_public
from tests.web.public.leaks import HIDDEN, LOCALES

ANY = like_contains_pattern("")
HIDDEN_ALL = (*HIDDEN, "secret_talk", "draft_parent")


@pytest.fixture
async def fx(public_locales_client) -> PublicFixture:
    return await seed_public(public_locales_client)


async def _all(client, tenant, **kw):
    with tenant_scope(tenant):
        async with client.db_state.session_factory() as session:
            return await contract.search_events(
                session, tenant_id=tenant, pattern=ANY, limit=50, upcoming_only=False, **kw
            )


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("hidden", HIDDEN_ALL)
async def test_hidden_event_absent_from_the_contract(public_locales_client, fx, hidden, locale):
    event = fx.hidden[hidden]
    async with public_locales_client.db_state.session_factory() as session:
        with tenant_scope("default"):
            got = await contract.get_event_card(
                session, tenant_id="default", event_id=event.id, locale=locale
            )
    assert got is None
    cards = await _all(public_locales_client, "default", locale=locale)
    seen = " ".join(f"{c.id} {c.title} {c.path} {c.ics_path} {c.summary}" for c in cards)
    assert str(event.id) not in seen
    for slug in (fx.slug(event), fx.slugs.get(f"{event.id}:de", fx.slug(event))):
        assert slug not in seen
        assert slug.title() not in seen
    assert {c.id for c in cards} <= {e.id for e in fx.public_events}


async def test_a_card_is_the_public_projection_only(public_locales_client, fx):
    cards = await _all(public_locales_client, "default")
    assert {c.id for c in cards} == {
        fx.one_off.id,
        fx.series.id,
        fx.conf.id,
        fx.talk.id,
        fx.orphan.id,
    }
    allowed = {
        "id", "title", "summary", "starts_at", "ends_at", "all_day", "start_date", "end_date",
        "timezone", "occurrence_start", "attendance_mode", "venue_name", "address",
        "image_url", "path", "ics_path", "locale", "cancelled",
    }  # fmt: skip
    for card in cards:
        assert set(type(card).model_fields) == allowed


@pytest.mark.unbound_tenant
async def test_other_tenant_absent_from_the_contract(public_multi_client):
    mine = await seed_public(public_multi_client, tag="-a", tenant="a")
    theirs = await seed_public(public_multi_client, tag="-b", tenant="b")
    cards = await _all(public_multi_client, "a")
    assert {c.id for c in cards} <= {e.id for e in mine.public_events}
    assert {c.id for c in cards}.isdisjoint({e.id for e in theirs.public_events})
    async with public_multi_client.db_state.session_factory() as session:
        for event in theirs.public_events:
            got = await contract.get_event_card(session, tenant_id="a", event_id=event.id)
            assert got is None, "b's published event, asked as a"
