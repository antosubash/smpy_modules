"""Phase 4 review, the index and payload halves. Each test failed before its fix.

Two subjects here, the provider half is in
``test_review_fixes_round4_providers.py``:

* a provider registered *after* a type was stored must not take that type
  offline (the blocker: the virtual-key refusal ran on every read);
* an expansion must line up with the payload it is rendered beside, and must
  resolve only against the target type the field declares.
"""

from __future__ import annotations

import logging

import pytest
from sm_records.index import IndexEntry, IndexKind, VirtualField, register_index_provider
from sm_records.models import Record
from sm_records.schema.compile import PayloadValidationError
from sqlalchemy import select

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_VIEWER, roles
from tests.relation_helpers import field, library, make_record, make_type

API = "/api/records"


def indexed(key: str, type_: str = "text") -> dict:
    """``relation_helpers.field`` puts its kwargs in ``options``, and
    ``indexed`` is a flag beside them."""
    return {**field(key, type_), "indexed": True}


def yielding(*entries):
    def _provider(record, rtype):
        for kind, key, value in entries:
            yield IndexEntry(kind=kind, field_key=key, value=value)

    return _provider


# ---------------------------------------------------------------------------
# B1 — a shadowing virtual key must not take a stored type offline
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


async def test_declaring_a_virtual_key_is_still_refused_when_saving(client):
    register_index_provider(
        yielding((IndexKind.TEXT, "bucket", "x")), fields=[VirtualField("bucket", IndexKind.TEXT)]
    )
    resp = await client.post(
        f"{API}/types",
        json={"key": "widget", "label": "Widget", "fields": [field("bucket", "text")]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422
    assert "index provider" in resp.json()["errors"][0]["message"]


# ---------------------------------------------------------------------------
# M2 / M4 — what ``?expand=`` resolves, and what it lines up with
# ---------------------------------------------------------------------------


async def _retype_payload(db_state, uuid: str, data: dict) -> None:
    """Write a payload the current write path would refuse — the rows §9 says
    exist from before ``check_targets``/``_check_ref_list`` did."""
    async with db_state.session_factory() as session:
        row = (await session.execute(select(Record).where(Record.uuid == uuid))).scalars().first()
        row.data = data
        session.add(row)
        await session.commit()


async def test_a_ref_naming_another_type_than_the_field_declares_is_dangling(client, records_app):
    _app, db_state = records_app
    await make_type(client, "secret", [field("name", "text")], allowed_roles=[ROLE_EDITOR])
    hidden = await make_record(client, "secret", {"name": "Top Secret"}, actor=ROLE_EDITOR)
    await library(client)
    author = await make_record(client, "author", {"name": "Visible"})
    book = await make_record(
        client, "book", {"name": "B", "author": {"type": "author", "uuid": author["uuid"]}}
    )
    await _retype_payload(
        db_state, book["uuid"], {"name": "B", "author": {"type": "secret", "uuid": hidden["uuid"]}}
    )

    got = await client.get(
        f"{API}/types/book/records/{book['uuid']}?expand=author", headers=roles(ROLE_VIEWER)
    )
    ref = got.json()["expanded"]["author"][0]
    assert ref["dangling"] is True
    assert ref["display_title"] is None
    assert "Top Secret" not in got.text


async def test_a_null_inside_a_to_many_relation_is_refused_on_write(client):
    await library(client, many=True)
    author = await make_record(client, "author", {"name": "One"})
    resp = await client.post(
        f"{API}/types/book/records",
        json={
            "data": {
                "name": "B",
                "author": [{"type": "author", "uuid": author["uuid"]}, None],
            }
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "author"
    assert "entry 1" in resp.json()["errors"][0]["message"]


async def test_a_stored_null_keeps_its_slot_in_the_expansion(client, records_app):
    """The write path refuses one now; a row that already holds one must still
    render, and ``expanded[i]`` must still be ``data[i]``."""
    _app, db_state = records_app
    await library(client, many=True)
    one = await make_record(client, "author", {"name": "One"})
    two = await make_record(client, "author", {"name": "Two"})
    book = await make_record(
        client, "book", {"name": "B", "author": [{"type": "author", "uuid": one["uuid"]}]}
    )
    await _retype_payload(
        db_state,
        book["uuid"],
        {
            "name": "B",
            "author": [
                {"type": "author", "uuid": one["uuid"]},
                None,
                {"type": "author", "uuid": two["uuid"]},
            ],
        },
    )

    got = await client.get(
        f"{API}/types/book/records/{book['uuid']}?expand=author", headers=roles(ADMIN)
    )
    expanded = got.json()["expanded"]["author"]
    assert len(expanded) == len(got.json()["data"]["author"]) == 3
    assert [ref["display_title"] for ref in expanded] == ["One", None, "Two"]
    assert expanded[1]["dangling"] is True


def test_the_compiled_validator_names_the_offending_entry():
    from sm_records.schema._builders import annotation_for
    from sm_records.schema.compile import build_model, validate_payload
    from sm_records.schema.fields import validate_fields

    defs = validate_fields(
        [field("author", "relation", target_type="author", many=True)], on_save=True
    )
    assert annotation_for(defs[0], required=False) is not None
    model = build_model("book", 1, defs)
    with pytest.raises(PayloadValidationError) as exc:
        validate_payload(model, {"author": ["not-an-object"]})
    assert exc.value.errors[0]["field"] == "author"
