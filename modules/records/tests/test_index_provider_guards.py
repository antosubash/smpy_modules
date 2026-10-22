"""What an index provider may claim, what it may write, and what it may not
take offline.

A provider projects rows — design §7.6 sells it as *additive projection*, and
§7.7's argument is that index bugs produce wrong answers rather than slow
ones. So it does not get to claim keys nothing can read, write the wrong kind
under one, or invent references; and one registered *after* a type was stored
must not take that type offline.
"""

from __future__ import annotations

import logging

import pytest
from sm_records.index import IndexKind, VirtualField, register_index_provider
from sm_records.index import providers as registry
from sm_records.models import IndexRef, IndexText
from sqlalchemy import func, select

from tests.app_harness import ADMIN, roles
from tests.index_provider_helpers import indexed, yielding
from tests.relation_helpers import field, make_record, make_type

API = "/api/records"


# ---------------------------------------------------------------------------
# a shadowing virtual key must not take a stored type offline
# ---------------------------------------------------------------------------


async def test_a_type_declaring_a_later_virtual_key_still_reads(client):
    await make_type(
        client,
        "product",
        [field("name", "text"), indexed("bucket")],
        is_public=True,
    )
    created = await make_record(client, "product", {"name": "P", "bucket": "declared"})
    await client.app.state.records_module.on_startup(client.app)

    register_index_provider(
        yielding((IndexKind.TEXT, "bucket", "from-provider")),
        fields=[VirtualField("bucket", IndexKind.TEXT)],
    )

    listed = await client.get(f"{API}/types/product/records", headers=roles(ADMIN))
    one = await client.get(f"{API}/types/product/records/{created['uuid']}", headers=roles(ADMIN))
    anonymous = await client.get(f"{API}/public/product")
    assert (listed.status_code, one.status_code, anonymous.status_code) == (200, 200, 200)
    assert listed.json()["total"] == 1


async def test_the_declared_field_wins_the_filter_over_the_virtual_one(client, caplog):
    """``index.query._resolve``'s promise, now reachable at all: the type's own
    definition decides the filter — its kind, its ``many`` reading — and the
    collision is one warning per type rather than a refusal. The provider's
    rows land in the same table under the same key and are therefore still
    matched by a value filter; that is the cost of not breaking a type that
    works, and it is why the collision is logged."""
    await make_type(client, "product", [field("name", "text"), indexed("bucket")])
    await make_record(client, "product", {"name": "P", "bucket": "declared"})
    register_index_provider(
        yielding((IndexKind.TEXT, "bucket", "from-provider")),
        fields=[VirtualField("bucket", IndexKind.TEXT)],
    )
    # Rewritten with the provider registered, so both projections have rows.
    listed = await client.get(f"{API}/types/product/records", headers=roles(ADMIN))
    uuid = listed.json()["items"][0]["uuid"]
    await client.put(
        f"{API}/types/product/records/{uuid}",
        json={"data": {"name": "P", "bucket": "declared"}, "expected_version": 1},
        headers=roles(ADMIN),
    )

    async def total(value: str) -> int:
        resp = await client.get(
            f"{API}/types/product/records",
            params=[("filter", f"bucket:eq:{value}")],
            headers=roles(ADMIN),
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["total"]

    with caplog.at_level(logging.WARNING):
        assert await total("declared") == 1
        assert await total("declared") == 1
    warned = [rec for rec in caplog.records if "also projects" in rec.getMessage()]
    assert len(warned) == 1, "once per type, not once per request"


# ---------------------------------------------------------------------------
# what a provider may claim, and what it may write
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key", ["status", "position", "_orphaned", "id", "", "Not A Key", "x" * 65]
)
def test_register_refuses_a_virtual_key_nothing_could_read(key):
    with pytest.raises(ValueError, match="virtual field"):
        registry.register(yielding(), fields=[VirtualField(key, IndexKind.TEXT)])
    assert key not in registry.virtual_fields()


async def test_a_kind_that_disagrees_with_the_declaration_is_dropped_and_logged(
    client, records_app, caplog
):
    _app, db_state = records_app
    await make_type(client, "product", [field("name", "text")])
    register_index_provider(
        yielding((IndexKind.TEXT, "price_bucket", "100")),
        fields=[VirtualField("price_bucket", IndexKind.NUMBER)],
    )
    with caplog.at_level(logging.WARNING):
        for name in ("one", "two"):
            await make_record(client, "product", {"name": name})

    async with db_state.session_factory() as session:
        rows = (
            await session.execute(
                select(func.count(IndexText.id)).where(IndexText.field_key == "price_bucket")
            )
        ).scalar_one()
    assert rows == 0
    logged = [rec for rec in caplog.records if "price_bucket" in rec.getMessage()]
    assert len(logged) == 1, "once per provider and key, not once per record"


async def test_a_provider_cannot_invent_a_reference(client, records_app):
    """A ``REF`` row is load-bearing — it blocks deletes and fills the delete
    dialog — so one naming a type id that does not exist is dropped."""
    _app, db_state = records_app
    await make_type(client, "author", [field("name", "text")])
    await make_type(client, "note", [field("name", "text")])
    author = await make_record(client, "author", {"name": "A"})

    register_index_provider(
        yielding((IndexKind.REF, "haunt", (author["uuid"], 99999))),
        fields=[VirtualField("haunt", IndexKind.REF)],
    )
    await make_record(client, "note", {"name": "unrelated"})

    async with db_state.session_factory() as session:
        refs = (await session.execute(select(func.count(IndexRef.id)))).scalar_one()
    assert refs == 0

    panel = await client.get(
        f"{API}/types/author/records/{author['uuid']}/referrers", headers=roles(ADMIN)
    )
    assert panel.json()["total"] == 0
    deleted = await client.delete(
        f"{API}/types/author/records/{author['uuid']}", headers=roles(ADMIN)
    )
    assert deleted.status_code == 204
