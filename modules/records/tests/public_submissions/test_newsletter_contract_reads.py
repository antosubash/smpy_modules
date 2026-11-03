"""The newsletter contract's subscriber reads (newsletter PR 1, Task 1)."""

from __future__ import annotations

import pytest
from sm_records.contracts.newsletter import (
    MAX_SUBSCRIBER_BATCH,
    SubscriberFilterError,
    count_subscribers,
    iter_subscribers,
    subscribers_by_uuid,
)

from tests.support.app_harness import ADMIN, roles
from tests.support.newsletter_contract import TENANT, unbound
from tests.support.newsletter_http import LIST, records_of
from tests.support.public_submissions_support import create


async def _iter(client, **kw):
    async with client.db_state.session_factory() as db:
        return await iter_subscribers(db, tenant_id=TENANT, type_key=LIST, **kw)


async def _count(client, **kw):
    async with client.db_state.session_factory() as db:
        return await count_subscribers(db, tenant_id=TENANT, type_key=LIST, **kw)


async def _uuid_of(client, email: str) -> str:
    hits, _ = await _iter(client)
    return next(h.uuid for h in hits if h.email == email)


async def test_iter_returns_only_confirmed_untrashed(audience):
    hits, nxt = await _iter(audience)
    assert [h.email for h in hits] == ["ada@example.org", "bob@example.org"]
    assert nxt is None
    assert all(h.status == "confirmed" and h.confirmed_at and not h.trashed for h in hits)
    assert hits[0].tags == ["a"] and hits[0].first_name is None
    uuid = hits[0].uuid
    gone = await audience.delete(f"/api/records/types/{LIST}/records/{uuid}", headers=roles(ADMIN))
    assert gone.status_code < 300, gone.text
    hits, _ = await _iter(audience)
    assert [h.email for h in hits] == ["bob@example.org"]
    assert await _count(audience) == 1


async def test_iter_filters_by_tag(audience):
    hits, _ = await _iter(audience, filters=["tags:eq:a"])
    assert [h.email for h in hits] == ["ada@example.org"]
    assert await _count(audience, filters=["tags:eq:a"]) == 1
    hits, _ = await _iter(audience, filters=["tags:in:a,b"])
    assert len(hits) == 2
    assert await _count(audience) == 2


async def test_iter_pages_by_after(audience):
    first, nxt = await _iter(audience, limit=1)
    assert len(first) == 1 and nxt is not None
    second, nxt = await _iter(audience, limit=1, after=nxt)
    assert len(second) == 1 and second[0].uuid != first[0].uuid
    assert nxt is None, "nothing follows the last hit"


async def test_bad_filter_raises_reason(audience):
    with pytest.raises(SubscriberFilterError) as unknown:
        await _iter(audience, filters=["nope:eq:x"])
    assert unknown.value.reason == "unknown"
    with pytest.raises(SubscriberFilterError) as malformed:
        await _iter(audience, filters=["tags:eq"])
    assert malformed.value.reason == "malformed"
    with pytest.raises(SubscriberFilterError) as counted:
        await _count(audience, filters=["nope:eq:x"])
    assert counted.value.reason == "unknown"


async def test_wrong_tenant_sees_nothing(audience):
    # Nothing bound upstream: only the tenant the call names is read.
    with unbound():
        async with audience.db_state.session_factory() as db:
            assert await iter_subscribers(db, tenant_id="other", type_key=LIST) == ([], None)
            assert await count_subscribers(db, tenant_id="other", type_key=LIST) == 0
            with pytest.raises(ValueError):
                await iter_subscribers(db, tenant_id="bad tenant!", type_key=LIST)
            with pytest.raises(ValueError):
                await count_subscribers(db, tenant_id="bad tenant!", type_key=LIST)
            with pytest.raises(ValueError):
                await subscribers_by_uuid(db, tenant_id="bad tenant!", type_key=LIST, uuids=["x"])
            found = await subscribers_by_uuid(db, tenant_id="other", type_key=LIST, uuids=["x"])
            assert found == {}


async def test_by_uuid_any_status(audience):
    rows = await records_of(audience)
    uuids = [r["uuid"] for r in rows]
    pending = next(r["uuid"] for r in rows if r["data"]["sm_status"] == "pending")
    async with audience.db_state.session_factory() as db:
        found = await subscribers_by_uuid(
            db, tenant_id=TENANT, type_key=LIST, uuids=[*uuids, "nope"]
        )
    assert set(found) == set(uuids) and len(found) == 3
    assert found[pending].status == "pending"
    assert not hasattr(found[pending], "sm_nonce")
    assert found[pending].tags == ["a", "b"]


async def test_by_uuid_includes_trash(audience):
    uuid = await _uuid_of(audience, "ada@example.org")
    await audience.delete(f"/api/records/types/{LIST}/records/{uuid}", headers=roles(ADMIN))
    async with audience.db_state.session_factory() as db:
        found = await subscribers_by_uuid(db, tenant_id=TENANT, type_key=LIST, uuids=[uuid])
    assert found[uuid].trashed is True


@pytest.mark.parametrize("limit", [0, MAX_SUBSCRIBER_BATCH + 1, True, -1, "5", None])
async def test_limit_checked(audience, limit):
    with pytest.raises(ValueError):
        await _iter(audience, limit=limit)


async def test_by_uuid_batch_checked(audience):
    async with audience.db_state.session_factory() as db:
        with pytest.raises(ValueError):
            await subscribers_by_uuid(
                db,
                tenant_id=TENANT,
                type_key=LIST,
                uuids=["x"] * (MAX_SUBSCRIBER_BATCH + 1),
            )


async def test_not_a_list(audience):
    assert (await create(audience, "contact")).status_code == 201
    async with audience.db_state.session_factory() as db:
        with pytest.raises(SubscriberFilterError) as err:
            await iter_subscribers(db, tenant_id=TENANT, type_key="contact")
        assert err.value.reason == "not_a_list"
        with pytest.raises(SubscriberFilterError):
            await count_subscribers(db, tenant_id=TENANT, type_key="contact")
