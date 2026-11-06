"""The newsletter contract's admin reads (newsletter PR 6, Task 1)."""

from __future__ import annotations

import pytest
from simple_module_db.listeners import TenantIsolationError, current_tenant_id
from sm_records.contracts.newsletter_admin import (
    SubscriberFilterError,
    browse_subscribers,
    list_fields,
    subscriber_admin_url,
    subscriber_status_counts,
)

from tests.support.app_harness import ADMIN, roles
from tests.support.newsletter_contract import TENANT, seed_list, session, unbound, uuid_of
from tests.support.newsletter_http import LIST
from tests.support.public_submissions_support import create

ALL = ["cy@example.org", "bob@example.org", "ada@example.org"]


async def _browse(client, tenant=TENANT, **kw):
    async with session(client) as db:
        return await browse_subscribers(db, tenant_id=tenant, type_key=LIST, **kw)


async def _emails(client, **kw):
    return [h.email for h in (await _browse(client, **kw)).items]


async def test_list_fields_has_tags_with_choices(audience):
    async with session(audience) as db:
        fields = {f.key: f for f in await list_fields(db, tenant_id=TENANT, type_key=LIST)}
    tags = fields["tags"]
    assert tags.many is True and tags.system is False
    assert [(c.value, c.label) for c in tags.choices] == [("a", "A"), ("b", "B")]
    assert fields["sm_email"].system is True and fields["sm_status"].system is True
    assert "sm_nonce" not in fields


async def test_list_fields_unknown_list_is_empty_and_not_a_list_raises(audience):
    with unbound():
        async with session(audience) as db:
            assert await list_fields(db, tenant_id="other", type_key=LIST) == []
    assert (await create(audience, "contact")).status_code == 201
    async with session(audience) as db:
        with pytest.raises(SubscriberFilterError) as err:
            await list_fields(db, tenant_id=TENANT, type_key="contact")
        assert err.value.reason == "not_a_list"


async def test_browse_includes_pending_newest_first(audience):
    page = await _browse(audience)
    assert [h.email for h in page.items] == ALL and page.total == 3


async def test_browse_status_filter(audience):
    assert await _emails(audience, status="pending") == ["cy@example.org"]


async def test_browse_search_is_case_insensitive_and_literal(audience):
    assert await _emails(audience, search="ADA@") == ["ada@example.org"]
    assert await _emails(audience, search="%") == []


async def test_browse_tag_filter(audience):
    assert await _emails(audience, filters=["tags:eq:a"]) == ["cy@example.org", "ada@example.org"]


async def test_browse_offset_pages(audience):
    page = await _browse(audience, limit=1, offset=1)
    assert [h.email for h in page.items] == ["bob@example.org"] and page.total == 3


async def test_browse_excludes_trash(audience):
    uuid = await uuid_of(audience, "ada@example.org")
    gone = await audience.delete(f"/api/records/types/{LIST}/records/{uuid}", headers=roles(ADMIN))
    assert gone.status_code < 300
    page = await _browse(audience)
    assert [h.email for h in page.items] == ALL[:2] and page.total == 2


async def test_status_counts(audience):
    async with session(audience) as db:
        counts = await subscriber_status_counts(db, tenant_id=TENANT, type_key=LIST)
        tagged = await subscriber_status_counts(
            db, tenant_id=TENANT, type_key=LIST, filters=["tags:eq:a"]
        )
    with unbound():
        async with session(audience) as db:
            none = await subscriber_status_counts(db, tenant_id="other", type_key=LIST)
    assert counts == {"pending": 1, "confirmed": 2, "unsubscribed": 0}
    assert tagged == {"pending": 1, "confirmed": 1, "unsubscribed": 0}
    assert none == {"pending": 0, "confirmed": 0, "unsubscribed": 0}


async def test_browse_pins_the_tenant(audience):
    with unbound():
        await seed_list(audience.db_state, "other", "zed@example.org")
    assert "zed@example.org" not in await _emails(audience)
    with unbound():
        assert await _emails(audience, tenant="other") == ["zed@example.org"]


async def test_bound_other_tenant_raises(audience):
    token = current_tenant_id.set(TENANT)
    try:
        async with session(audience) as db:
            with pytest.raises(TenantIsolationError):
                await browse_subscribers(db, tenant_id="other", type_key=LIST)
            with pytest.raises(TenantIsolationError):
                await subscriber_status_counts(db, tenant_id="other", type_key=LIST)
            with pytest.raises(TenantIsolationError):
                await list_fields(db, tenant_id="other", type_key=LIST)
    finally:
        current_tenant_id.reset(token)


@pytest.mark.parametrize(
    "kw",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"offset": -1},
        {"offset": 100_001},
        {"status": "x"},
        {"search": "a" * 201},
        {"search": "a\x00b"},
    ],
)
async def test_browse_refuses_bad_arguments(audience, kw):
    with pytest.raises(ValueError):
        await _browse(audience, **kw)


async def test_browse_malformed_term(audience):
    with pytest.raises(SubscriberFilterError) as err:
        await _browse(audience, filters=["nope"])
    assert err.value.reason == "malformed"
    with pytest.raises(SubscriberFilterError) as err:
        await _browse(audience, filters=["nope:eq:x"])
    assert err.value.reason == "unknown"


def test_subscriber_admin_url():
    assert subscriber_admin_url("news", None) == "/admin/records/news"
    assert subscriber_admin_url("news", "ab12") == "/admin/records/news/ab12"
    assert subscriber_admin_url("a b", "x/y") == "/admin/records/a%20b/x%2Fy"
