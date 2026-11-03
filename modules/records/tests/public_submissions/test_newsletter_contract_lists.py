"""The newsletter contract's list discovery and trash-aware unsubscribed walk.

Newsletter PR 2 (plan amendments 3 and 6, ruling R5): the newsletter module's
hourly suppression reconcile asks records which tenants own a list
(:func:`subscription_list_tenants`), which lists each one owns
(:func:`subscription_lists`), and who left a list including the trash
(``include_trashed=True``), so an unsubscribe whose event was lost survives
the subscriber's purge.
"""

from __future__ import annotations

from typing import Any

import pytest
from simple_module_db import no_tenant
from simple_module_db.listeners import TenantIsolationError
from sm_records.contracts.newsletter import (
    count_subscribers,
    iter_subscribers,
    subscription_list_tenants,
    subscription_lists,
)
from sm_records.core import events
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.records.services import records as record_service
from sm_records.records.services import types as type_service
from sm_records.records.services._common import utcnow

from tests.support.app_harness import ADMIN, roles
from tests.support.newsletter_contract import TAGS, TENANT, join, session, unbound
from tests.support.newsletter_http import LIST, follow, list_config, list_fields
from tests.support.public_submissions_support import contact_fields, create, form_config


async def _seed(
    db_state: Any,
    tenant: str,
    key: str,
    *,
    config: dict[str, Any] | None,
    leavers: tuple[str, ...] = (),
    trash: bool = False,
) -> None:
    """In ``tenant``, the type ``key`` and one unsubscribed record per address
    in ``leavers`` (each trashed when ``trash``), in a session of its own."""
    settings = RecordsSettings()
    subscription = (config or {}).get("kind") == "subscription"
    fields = [*list_fields(), TAGS] if subscription else contact_fields()
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            rtype = await type_service.create_type(
                db,
                key=key,
                label=key,
                fields_raw=fields,
                public_submissions=config,
                settings=settings,
            )
            for email in leavers:
                record = await record_service.create_record(
                    db,
                    rtype,
                    data={},
                    settings=settings,
                    system={
                        "sm_email": email,
                        "sm_status": "unsubscribed",
                        "sm_confirmed_at": utcnow(),
                        "sm_locale": "en",
                        "sm_nonce": "0" * 32,
                    },
                )
                if trash:
                    await record_service.soft_delete_record(db, rtype, record, settings=settings)
            await events.commit(db)


async def _lists(client, tenant: str) -> list[str]:
    async with session(client) as db:
        return await subscription_lists(db, tenant_id=tenant)


async def _tenants(client) -> list[str]:
    async with session(client) as db:
        return await subscription_list_tenants(db)


async def _left(client, tenant: str = TENANT, **kw) -> list[tuple[str, bool]]:
    """Every unsubscribed hit, walked page by page, as ``(email, trashed)``."""
    out: list[tuple[str, bool]] = []
    after: int | None = 0
    async with session(client) as db:
        while after is not None:
            hits, after = await iter_subscribers(
                db, tenant_id=tenant, type_key=LIST, status="unsubscribed", after=after, **kw
            )
            out.extend((h.email, h.trashed) for h in hits)
    return out


async def _count_left(client, tenant: str = TENANT, **kw) -> int:
    async with session(client) as db:
        return await count_subscribers(
            db, tenant_id=tenant, type_key=LIST, status="unsubscribed", **kw
        )


async def _leave_and_trash(client, email: str) -> None:
    """``email`` signs up, confirms, unsubscribes by link and is then trashed."""
    tokens = await join(client, email, ["a"], confirm=True)
    assert (await follow(client, "unsubscribe", tokens["unsubscribe"])).status_code == 200
    uuid = next(h.uuid for h in await _all_left(client) if h.email == email)
    gone = await client.delete(f"/api/records/types/{LIST}/records/{uuid}", headers=roles(ADMIN))
    assert gone.status_code < 300, gone.text


async def _all_left(client):
    async with session(client) as db:
        hits, _ = await iter_subscribers(db, tenant_id=TENANT, type_key=LIST, status="unsubscribed")
    return hits


# --- subscription_lists ----------------------------------------------------------


async def test_lists_are_the_tenants_subscription_keys_sorted(audience):
    assert (await create(audience, "contact")).status_code == 201, "a form is not a list"
    resp = await create(audience, "alpha", fields=list_fields(), config=list_config())
    assert resp.status_code == 201, resp.text
    await _seed(audience.db_state, TENANT, "plain", config=None)
    assert await _lists(audience, TENANT) == ["alpha", LIST]


async def test_a_deleted_list_is_not_listed(audience):
    resp = await create(audience, "gone", fields=list_fields(), config=list_config())
    assert resp.status_code == 201, resp.text
    deleted = await audience.delete(
        "/api/records/types/gone?confirm_record_count=0", headers=roles(ADMIN)
    )
    assert deleted.status_code == 204, deleted.text
    assert await _lists(audience, TENANT) == [LIST]


async def test_lists_never_name_another_tenants_list(audience):
    with unbound():
        await _seed(audience.db_state, "b", "theirs", config=list_config())
        await _seed(audience.db_state, "c", "contact", config=form_config())
        assert await _lists(audience, TENANT) == [LIST]
        assert await _lists(audience, "b") == ["theirs"]
        assert await _lists(audience, "c") == [], "a tenant whose only type is a form"
        assert await _lists(audience, "nobody") == []


async def test_lists_check_the_tenant(audience):
    with unbound(), pytest.raises(ValueError):
        await _lists(audience, "bad tenant!")
    with pytest.raises(TenantIsolationError):
        await _lists(audience, "other")


# --- subscription_list_tenants ---------------------------------------------------


async def test_tenants_owning_a_list_unbound_and_in_no_tenant(audience):
    with unbound():
        await _seed(audience.db_state, "b", LIST, config=list_config())
        await _seed(audience.db_state, "c", "contact", config=form_config())
        await _seed(audience.db_state, "d", "plain", config=None)
        assert await _tenants(audience) == ["b", TENANT]
    with no_tenant():
        assert await _tenants(audience) == ["b", TENANT]


async def test_tenants_refused_under_a_bound_tenant(audience):
    # The harness binds ``default``, as a request does: no enumerating others.
    with pytest.raises(TenantIsolationError):
        await _tenants(audience)


# --- include_trashed ---------------------------------------------------------------


async def test_trashed_leavers_walk_only_with_include_trashed(audience):
    await _leave_and_trash(audience, "dee@example.org")
    tokens = await join(audience, "eve@example.org", ["b"], confirm=True)
    assert (await follow(audience, "unsubscribe", tokens["unsubscribe"])).status_code == 200
    assert await _left(audience) == [("eve@example.org", False)]
    assert await _count_left(audience) == 1
    walked = await _left(audience, include_trashed=True)
    assert walked == [("dee@example.org", True), ("eve@example.org", False)]
    assert await _count_left(audience, include_trashed=True) == 2
    paged = await _left(audience, include_trashed=True, limit=1)
    assert paged == walked, "one page at a time walks every row once"


async def test_include_trashed_never_reaches_confirmed_or_pending(audience):
    await _leave_and_trash(audience, "dee@example.org")
    walked = await _left(audience, include_trashed=True)
    assert [e for e, _ in walked] == ["dee@example.org"], "ada and bob stay out, cy too"


async def test_include_trashed_is_tenant_pinned(audience):
    with unbound():
        await _seed(
            audience.db_state, "b", LIST, config=list_config(), leavers=("bea@x.org",), trash=True
        )
        assert await _left(audience, "b", include_trashed=True) == [("bea@x.org", True)]
        assert await _left(audience, TENANT, include_trashed=True) == []
        assert await _count_left(audience, TENANT, include_trashed=True) == 0
        assert await _count_left(audience, "b", include_trashed=True) == 1


@pytest.mark.parametrize("status", ["confirmed", "pending"])
async def test_include_trashed_needs_unsubscribed(audience, status):
    async with session(audience) as db:
        with pytest.raises(ValueError):
            await iter_subscribers(
                db, tenant_id=TENANT, type_key=LIST, status=status, include_trashed=True
            )
        with pytest.raises(ValueError):
            await count_subscribers(
                db, tenant_id=TENANT, type_key=LIST, status=status, include_trashed=True
            )


async def test_include_trashed_refused_before_any_query(audience, monkeypatch):
    from sm_records.public_submissions import campaign_reads

    async def boom(*_a, **_kw):
        raise AssertionError("queried")

    monkeypatch.setattr(campaign_reads, "list_type", boom)
    async with session(audience) as db:
        with pytest.raises(ValueError):
            await iter_subscribers(db, tenant_id=TENANT, type_key=LIST, include_trashed=True)
        with pytest.raises(ValueError):
            await count_subscribers(db, tenant_id=TENANT, type_key=LIST, include_trashed=True)


@pytest.mark.parametrize("flag", [1, 0, "yes", None])
async def test_include_trashed_must_be_a_bool(audience, flag):
    with pytest.raises(ValueError):
        await _left(audience, include_trashed=flag)
    with pytest.raises(ValueError):
        await _count_left(audience, include_trashed=flag)
