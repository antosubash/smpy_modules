"""A registration can never be attached to, or shown for, an external (subscribed) item: seats
and registrations are keyed by an event's id, and nothing an external item has is one."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sm_events.calendar.plugins import registry
from sm_events.contracts import registration as contract
from sm_events.core.tenancy import tenant_scope

from tests.support.calendars import OWNER_P as OWNER
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID, install_provider, provider
from tests.support.subscriptions import seed_item
from tests.support.subscriptions_http import add, app_client, calendar, row, stub_launch

START = datetime(2027, 3, 10, 9, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _provider(monkeypatch):
    install_provider(monkeypatch, provider())
    yield
    registry.reset_registry()


async def _external(client, monkeypatch):
    """A subscription with one item; the ids an attacker could try for it."""
    stub_launch(monkeypatch)
    cid = await calendar(client, visibility="public")
    made = (await add(client, cid, OWNER, url="https://a.example.test/a.ics", public=True)).json()
    sub = await row(client, made["id"])
    async with client.db_state.session_factory() as db:
        item = await seed_item(db, sub, "u", START, title="Third party")
        await db.commit()
    return sub, item


def _ids(sub, item) -> list[uuid.UUID]:
    return [sub.id, uuid.UUID(int=item.id), uuid.uuid5(uuid.NAMESPACE_URL, str(item.id))]


async def test_the_registration_api_refuses_an_external_id_as_not_found(monkeypatch):
    async with app_client() as client:
        sub, item = await _external(client, monkeypatch)
        for ident in _ids(sub, item):
            got = await client.get(f"/api/events/events/{ident}/registrations", headers=OWNER)
            assert got.status_code == 404, ident


async def test_the_contract_knows_no_seat_or_offer_for_an_external_id(monkeypatch):
    async with app_client() as client:
        sub, item = await _external(client, monkeypatch)
        async with client.db_state.session_factory() as db:
            for ident in _ids(sub, item):
                key = str(ident)  # a well-formed key: the refusal is about the id
                with tenant_scope("default"):
                    offer = await contract.describe(
                        db, tenant_id="default", event_id=ident, occurrence_key=key,
                        provider=PROVIDER_ID, target=KNOWN_TARGET, locale="en",
                    )  # fmt: skip
                    admitted = await contract.admit(
                        db, tenant_id="default", event_id=ident, occurrence_key=key,
                        provider=PROVIDER_ID, target=KNOWN_TARGET, holder="h",
                    )  # fmt: skip
                    shown = await contract.summaries(
                        db, tenant_id="default", provider=PROVIDER_ID,
                        refs=[(ident, key)], locale="en",
                    )  # fmt: skip
                assert offer.state == "unavailable", ident
                assert (admitted.admitted, admitted.code) == (False, "event_unavailable")
                assert shown == {(ident, key): None}
