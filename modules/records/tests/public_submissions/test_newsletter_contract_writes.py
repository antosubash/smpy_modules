"""The newsletter contract's writes: ``unsubscribe``, ``set_tags`` and
``can_read_list`` (newsletter PR 1, Task 2; spec amendments 6-9).

A write is the caller's transaction: nothing is visible, and no event is
published, until the caller finishes the session (records' ``events.commit``,
which is ``finalize_session``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from simple_module_db.listeners import TenantIsolationError
from sm_records.contracts.events import RecordUpdated
from sm_records.contracts.newsletter import (
    SubscriberFilterError,
    SubscriberNotFound,
    can_read_list,
    set_tags,
    subscribers_by_uuid,
    unsubscribe,
)
from sm_records.core import events
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.models import Record, tables_for
from sm_records.public_submissions.campaign_reads import list_type
from sm_records.records.services.errors import ValidationFailed
from sqlalchemy import select
from sqlalchemy import update as sa_update

from tests.support.app_harness import ADMIN, roles
from tests.support.newsletter_contract import (
    TENANT,
    join,
    published,
    session,
    subscription_events,
    transitions,
    unbound,
    uuid_of,
)
from tests.support.newsletter_contract import unsubscribe_committed as _unsubscribe
from tests.support.newsletter_http import LIST, follow, signup
from tests.support.public_submissions_support import create, update

SETTINGS = RecordsSettings()


async def _hit(client, uuid: str, tenant: str = TENANT):
    async with session(client) as db:
        found = await subscribers_by_uuid(db, tenant_id=tenant, type_key=LIST, uuids=[uuid])
    return found.get(uuid)


async def _set_tags(client, uuid: str, **kw):
    async with session(client) as db:
        hit = await set_tags(
            db, tenant_id=TENANT, type_key=LIST, uuid=uuid, settings=SETTINGS, **kw
        )
        await events.commit(db)
    return hit


async def test_unsubscribe_suppresses_and_emits_once(audience):
    uuid = await uuid_of(audience, "ada@example.org")
    seen = subscription_events(audience)
    assert await _unsubscribe(audience, uuid) is True
    assert (await _hit(audience, uuid)).status == "unsubscribed"
    assert list(transitions(seen)) == [("confirmed", "unsubscribed")]
    assert await _unsubscribe(audience, uuid) is False
    assert len(seen) == 1, "the second call wrote nothing and announced nothing"


async def test_resignup_after_cutoff_is_kept(audience):
    tokens = await join(audience, "dee@example.org", ["a"], confirm=True)
    cutoff = datetime.now(UTC)
    assert (await follow(audience, "unsubscribe", tokens["unsubscribe"])).status_code == 200
    await join(audience, "dee@example.org", ["a"], confirm=True)
    uuid = await uuid_of(audience, "dee@example.org")
    assert await _unsubscribe(audience, uuid, cutoff=cutoff) is False
    assert (await _hit(audience, uuid)).status == "confirmed"


@pytest.mark.parametrize("stored", [None, "not a date"])
async def test_unsubscribe_with_cutoff_when_confirmed_at_is_unreadable(audience, stored):
    uuid = await uuid_of(audience, "ada@example.org")
    async with session(audience) as db:
        with tenant_scope(TENANT):
            rtype = await list_type(db, TENANT, LIST)
            cls = tables_for(rtype).record
            row = (await db.execute(select(cls).where(cls.uuid == uuid))).scalar_one()
            data = {k: v for k, v in row.data.items() if k != "sm_confirmed_at"}
            if stored is not None:
                data["sm_confirmed_at"] = stored
            await db.execute(
                sa_update(cls)
                .where(cls.id == row.id, cls.tenant_id == row.tenant_id)
                .values(data=data, version=row.version + 1)
                .execution_options(synchronize_session=False)
            )
            await events.commit(db)
    assert await _unsubscribe(audience, uuid, cutoff=datetime.now(UTC)) is True
    assert (await _hit(audience, uuid)).status == "unsubscribed"


async def test_an_old_link_while_pending_again_does_nothing(audience):
    tokens = await join(audience, "eve@example.org", ["a"], confirm=True)
    uuid = await uuid_of(audience, "eve@example.org")
    assert (await follow(audience, "unsubscribe", tokens["unsubscribe"])).status_code == 200
    assert (await signup(audience, "eve@example.org")).status_code == 202
    assert (await _hit(audience, uuid)).status == "pending"
    seen = subscription_events(audience)
    assert await _unsubscribe(audience, uuid, cutoff=datetime.now(UTC)) is False
    assert await _unsubscribe(audience, uuid) is False, "pending is a no-op even unconditionally"
    assert (await _hit(audience, uuid)).status == "pending" and seen == []


async def test_unsubscribe_unknown_and_trashed_are_false(audience):
    assert await _unsubscribe(audience, "f" * 32) is False
    uuid = await uuid_of(audience, "ada@example.org")
    gone = await audience.delete(f"/api/records/types/{LIST}/records/{uuid}", headers=roles(ADMIN))
    assert gone.status_code < 300, gone.text
    assert await _unsubscribe(audience, uuid) is False
    assert (await _hit(audience, uuid)).status == "confirmed"


async def test_unsubscribe_wrong_tenant_is_false(audience):
    uuid = await uuid_of(audience, "ada@example.org")
    with unbound():
        assert await _unsubscribe(audience, uuid, tenant="other") is False
    assert (await _hit(audience, uuid)).status == "confirmed"


async def test_writes_naming_another_bound_tenant_are_refused(audience):
    uuid = await uuid_of(audience, "ada@example.org")
    with pytest.raises(TenantIsolationError):
        await _unsubscribe(audience, uuid, tenant="other")
    async with session(audience) as db:
        with pytest.raises(TenantIsolationError):
            await set_tags(
                db, tenant_id="other", type_key=LIST, uuid=uuid, add=["b"], settings=SETTINGS
            )
        with pytest.raises(TenantIsolationError):
            await can_read_list(db, tenant_id="other", type_key=LIST, roles=None)


async def test_unsubscribe_refuses_a_naive_cutoff(audience):
    uuid = await uuid_of(audience, "ada@example.org")
    with pytest.raises(ValueError):
        await _unsubscribe(audience, uuid, cutoff=datetime(2026, 1, 1))


async def test_set_tags_adds_and_removes(audience):
    uuid = await uuid_of(audience, "ada@example.org")
    assert (await _set_tags(audience, uuid, add=["b", "a"], remove=[])).tags == ["a", "b"]
    assert (await _hit(audience, uuid)).tags == ["a", "b"]
    assert (await _set_tags(audience, uuid, remove=["a"])).tags == ["b"]
    hit = await _hit(audience, uuid)
    assert hit.tags == ["b"] and hit.status == "confirmed", "system values carried over"


async def test_set_tags_unknown_choice_refused(audience):
    uuid = await uuid_of(audience, "ada@example.org")
    async with session(audience) as db:
        with pytest.raises(ValidationFailed):
            await set_tags(
                db, tenant_id=TENANT, type_key=LIST, uuid=uuid, add=["zzz"], settings=SETTINGS
            )
        await events.commit(db)  # whatever the refusal left in the session
    assert (await _hit(audience, uuid)).tags == ["a"]


async def test_set_tags_missing_raises(audience):
    with pytest.raises(SubscriberNotFound):
        await _set_tags(audience, "f" * 32, add=["a"])
    with pytest.raises(ValueError):
        await _set_tags(audience, await uuid_of(audience, "ada@example.org"), add="a")


async def test_can_read_list(audience):
    assert (await create(audience, "contact")).status_code == 201
    narrowed = await update(audience, LIST, allowed_roles=["editor"])
    assert narrowed.status_code == 200, narrowed.text
    async with session(audience) as db:

        async def ok(key: str, roles) -> bool:
            return await can_read_list(db, tenant_id=TENANT, type_key=key, roles=roles)

        assert await ok(LIST, ["viewer"]) is False
        assert await ok(LIST, ["editor"]) is True
        assert await ok(LIST, None) is True
        assert await ok("contact", None) is False, "not a list"
        assert await ok("nosuch", None) is False


async def _version(client, uuid: str) -> int:
    async with session(client) as db:
        row = (await db.execute(select(Record).where(Record.uuid == uuid))).scalars().one()
        return row.version


async def test_set_tags_that_changes_nothing_writes_nothing(audience):
    uuid = await uuid_of(audience, "ada@example.org")  # ada has ["a"]
    before = await _version(audience, uuid)
    seen = published(audience, RecordUpdated)
    hit = await _set_tags(audience, uuid, add=["a"], remove=["b"])
    assert hit.tags == ["a"]
    assert await _version(audience, uuid) == before
    assert not seen, "no RecordUpdated for a no-op"


async def test_writes_on_a_form_type_raise_not_a_list(audience):
    assert (await create(audience, "contact")).status_code == 201
    async with session(audience) as db:
        with pytest.raises(SubscriberFilterError) as err:
            await unsubscribe(
                db,
                tenant_id=TENANT,
                type_key="contact",
                uuid="x",
                unless_confirmed_after=None,
                settings=SETTINGS,
            )
        assert err.value.reason == "not_a_list"
        with pytest.raises(SubscriberFilterError) as err:
            await set_tags(
                db, tenant_id=TENANT, type_key="contact", uuid="x", add=["a"], settings=SETTINGS
            )
        assert err.value.reason == "not_a_list"


async def test_set_tags_removing_from_a_subscriber_without_tags_writes_nothing(audience):
    await join(audience, "eve@example.org", [], confirm=True)
    uuid = await uuid_of(audience, "eve@example.org")
    async with session(audience) as db:  # a row whose data has no `tags` key at all
        row = (await db.execute(select(Record).where(Record.uuid == uuid))).scalars().one()
        row.data = {k: v for k, v in row.data.items() if k != "tags"}
        await events.commit(db)
    before = await _version(audience, uuid)
    seen = published(audience, RecordUpdated)
    hit = await _set_tags(audience, uuid, remove=["x"])
    assert hit.tags == []
    assert await _version(audience, uuid) == before
    assert not seen
