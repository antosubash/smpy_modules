"""The newsletter contract's reads: tenant binding and argument checks.

Every function binds the tenant it is given with records' ``tenant_scope``
semantics (spec amendment 6): naming another tenant while one is bound raises
``TenantIsolationError``, and with nothing bound a call sees only the tenant
it names. Also the ``status`` a walk may ask for and the checks on ``after``
and ``uuids``.
"""

from __future__ import annotations

import pytest
from simple_module_db.listeners import TenantIsolationError
from sm_records.contracts.newsletter import (
    SubscriberFilterError,
    count_subscribers,
    iter_subscribers,
    subscribers_by_uuid,
)

from tests.support.newsletter_contract import TENANT, join, seed_list, session, unbound
from tests.support.newsletter_http import LIST, follow
from tests.support.public_submissions_support import create


async def _hits(client, tenant: str, **kw) -> list[str]:
    async with session(client) as db:
        hits, _ = await iter_subscribers(db, tenant_id=tenant, type_key=LIST, **kw)
    return [h.email for h in hits]


async def test_naming_another_tenant_inside_a_bound_one_is_refused(audience):
    # The harness binds ``default`` around every test, as a single-tenant host does.
    async with session(audience) as db:
        with pytest.raises(TenantIsolationError):
            await iter_subscribers(db, tenant_id="other", type_key=LIST)
        with pytest.raises(TenantIsolationError):
            await count_subscribers(db, tenant_id="other", type_key=LIST)
        with pytest.raises(TenantIsolationError):
            await subscribers_by_uuid(db, tenant_id="other", type_key=LIST, uuids=["x"])
    assert len(await _hits(audience, TENANT)) == 2, "the bound tenant itself is a no-op"


async def test_two_tenants_with_the_same_list_never_see_each_other(audience):
    with unbound():
        other = await seed_list(audience.db_state, "b", "bea@example.org")
        assert await _hits(audience, "b") == ["bea@example.org"]
        assert await _hits(audience, TENANT) == ["ada@example.org", "bob@example.org"]
        async with session(audience) as db:
            assert await count_subscribers(db, tenant_id="b", type_key=LIST) == 1
            mine = await subscribers_by_uuid(db, tenant_id=TENANT, type_key=LIST, uuids=[other])
            theirs = await subscribers_by_uuid(db, tenant_id="b", type_key=LIST, uuids=[other])
        assert mine == {} and theirs[other].email == "bea@example.org"
        assert await _hits(audience, "nobody") == [], "nothing bound, a tenant with no list"


async def test_status_unsubscribed_walks_who_left(audience):
    tokens = await join(audience, "dee@example.org", ["a"], confirm=True)
    assert (await follow(audience, "unsubscribe", tokens["unsubscribe"])).status_code == 200
    assert "dee@example.org" not in await _hits(audience, TENANT)
    assert await _hits(audience, TENANT, status="unsubscribed") == ["dee@example.org"]
    async with session(audience) as db:
        left = await count_subscribers(db, tenant_id=TENANT, type_key=LIST, status="unsubscribed")
    assert left == 1
    with pytest.raises(ValueError):
        await _hits(audience, TENANT, status="pending")


@pytest.mark.parametrize("after", [-1, True, "3", None, 1.5])
async def test_after_checked(audience, after):
    with pytest.raises(ValueError):
        await _hits(audience, TENANT, after=after)


async def test_by_uuid_refuses_a_bare_string(audience):
    async with session(audience) as db:
        with pytest.raises(ValueError):
            await subscribers_by_uuid(db, tenant_id=TENANT, type_key=LIST, uuids="abc")


async def test_by_uuid_not_a_list(audience):
    assert (await create(audience, "contact")).status_code == 201
    async with session(audience) as db:
        with pytest.raises(SubscriberFilterError) as err:
            await subscribers_by_uuid(db, tenant_id=TENANT, type_key="contact", uuids=["x"])
    assert err.value.reason == "not_a_list"


def test_a_naive_stored_timestamp_is_utc():
    from datetime import UTC, datetime

    from sm_records.public_submissions.campaign_reads import moment

    assert moment("2026-01-02T03:04:05") == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert moment("2026-01-02T03:04:05+02:00").utcoffset().total_seconds() == 7200
    assert moment("not a date") is None and moment(None) is None
