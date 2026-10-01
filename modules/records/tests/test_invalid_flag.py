"""The stored ``invalid_since`` mark: what writes it and what clears it.

Design §8.3's "marked, not hidden" has always been derived on read. This is
what the column adds: a forced restrictive change marks exactly the records
that fail it and nothing else, an ordinary write of a marked record clears it,
and nothing that did not happen — a refused write, a refused change — leaves a
mark or takes one away. Re-deriving the marks is ``test_invalid_rescan``.

The helpers, including the two that write behind the API's back, are in
``invalid_support``.
"""

from __future__ import annotations

from sm_records.models import Record, RecordType
from sqlalchemy import select

from tests.app_harness import ADMIN, roles
from tests.invalid_support import (
    TYPES,
    field,
    force_required_sku,
    read,
    type_with,
)


async def test_a_forced_change_marks_exactly_the_records_that_fail(client):
    """Two records, one of which satisfies the new rule. The scan judges each
    one, so the mark has to land on one row and not on the other — a change
    that marked the whole type would be indistinguishable from "this type is
    broken" on every screen that reads the column."""
    state = await type_with(client, {"name": "Widget"}, {"name": "Gadget", "sku": "G-1"})
    await force_required_sku(client, state["type"])

    broken = await read(client, state["uuids"][0])
    fine = await read(client, state["uuids"][1])
    assert broken["invalid_since"] is not None
    assert fine["invalid_since"] is None
    # The derived list still says *what* is wrong; the column says only that
    # something is, and when.
    assert [entry["field"] for entry in broken["invalid"]] == ["sku"]
    assert fine["invalid"] == []


async def test_the_mark_reaches_a_list_response_where_the_derived_badge_cannot(client):
    """The whole point of storing it: a list turns the validator off
    (``record_list_read``), so ``invalid`` is empty for every row — and the
    column is there anyway."""
    state = await type_with(client, {"name": "Widget"})
    await force_required_sku(client, state["type"])

    page = (await client.get(f"{TYPES}/product/records", headers=roles(ADMIN))).json()
    (item,) = page["items"]
    assert item["invalid"] == []
    assert item["invalid_since"] is not None


async def test_a_later_clean_write_clears_the_mark(client):
    """§8.3's promise that a marked record is fixed by its next ordinary
    write, now observable."""
    state = await type_with(client, {"name": "Widget"})
    await force_required_sku(client, state["type"])
    uuid = state["uuids"][0]
    assert (await read(client, uuid))["invalid_since"] is not None

    fixed = await client.put(
        f"{TYPES}/product/records/{uuid}",
        json={"expected_version": 1, "data": {"name": "Widget", "sku": "W-1"}},
        headers=roles(ADMIN),
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["invalid_since"] is None
    assert (await read(client, uuid))["invalid_since"] is None


async def test_a_refused_write_leaves_the_mark_alone(client):
    """The clear is part of the write, so a write that does not happen does
    not clear anything — otherwise a 422 would launder a record clean."""
    state = await type_with(client, {"name": "Widget"})
    await force_required_sku(client, state["type"])
    uuid = state["uuids"][0]

    refused = await client.put(
        f"{TYPES}/product/records/{uuid}",
        json={"expected_version": 1, "data": {"name": "Widget"}},
        headers=roles(ADMIN),
    )
    assert refused.status_code == 422, refused.text
    assert (await read(client, uuid))["invalid_since"] is not None


async def test_a_refused_restrictive_change_marks_nothing(client):
    """The unforced apply scans with marking on — and is then refused, which
    rolls the request back. Nothing may survive that: the change did not
    happen, so the records do not fail anything that is stored."""
    state = await type_with(client, {"name": "Widget"})
    created = state["type"]
    refused = await client.put(
        f"{TYPES}/product",
        json={
            "expected_version": created["version"],
            "fields": [created["fields"][0], {**created["fields"][1], "required": True}],
        },
        headers=roles(ADMIN),
    )
    assert refused.status_code == 409, refused.text
    assert (await read(client, state["uuids"][0]))["invalid_since"] is None


async def _trash_and_restore(client, uuid: str) -> None:
    trashed = await client.delete(f"{TYPES}/product/records/{uuid}", headers=roles(ADMIN))
    assert trashed.status_code == 204, trashed.text
    restored = await client.post(f"{TYPES}/product/records/{uuid}/restore", headers=roles(ADMIN))
    assert restored.status_code == 200, restored.text


async def test_restoring_a_marked_record_keeps_the_mark(client):
    """A restore reindexes under the current schema and validates *nothing* —
    the payload comes back exactly as it went in — so it fixes nothing and has
    no business dropping a mark. Clearing it made the two representations of
    one fact disagree on the very next read: the derived list still named the
    failing field while the column said the record was fine."""
    state = await type_with(client, {"name": "Widget"})
    await force_required_sku(client, state["type"])
    uuid = state["uuids"][0]

    await _trash_and_restore(client, uuid)

    after = await read(client, uuid)
    assert [entry["field"] for entry in after["invalid"]] == ["sku"]
    assert after["invalid_since"] is not None


async def test_the_worklist_still_lists_a_restored_record(client):
    """What the column is *for*: the filter behind the hub count and the
    "Check records" worklist reads it, not the validator."""
    state = await type_with(client, {"name": "Widget"})
    await force_required_sku(client, state["type"])
    uuid = state["uuids"][0]

    await _trash_and_restore(client, uuid)

    page = await client.get(f"{TYPES}/product/records?filter=invalid:eq:true", headers=roles(ADMIN))
    assert page.status_code == 200, page.text
    assert [item["uuid"] for item in page.json()["items"]] == [uuid]
    assert page.json()["total"] == 1


async def test_a_bulk_restore_keeps_the_mark_too(client):
    """Bulk composes the single-record call, so it inherits this — stated as a
    test because "by composition" is a claim that stops being true silently."""
    state = await type_with(client, {"name": "Widget"})
    await force_required_sku(client, state["type"])
    uuid = state["uuids"][0]
    assert (
        await client.delete(f"{TYPES}/product/records/{uuid}", headers=roles(ADMIN))
    ).status_code == 204

    resp = await client.post(
        f"{TYPES}/product/records/bulk",
        json={"action": "restore", "uuids": [uuid]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    assert (await read(client, uuid))["invalid_since"] is not None


async def test_a_restored_record_that_was_fixed_is_still_cleared_by_its_next_write(client):
    """The mark surviving a restore is not the mark becoming permanent: the
    ordinary write §8.3 promises still clears it, restore or no restore."""
    state = await type_with(client, {"name": "Widget"})
    await force_required_sku(client, state["type"])
    uuid = state["uuids"][0]
    await _trash_and_restore(client, uuid)

    fixed = await client.put(
        f"{TYPES}/product/records/{uuid}",
        json={"expected_version": 1, "data": {"name": "Widget", "sku": "W-1"}},
        headers=roles(ADMIN),
    )
    assert fixed.status_code == 200, fixed.text
    assert (await read(client, uuid))["invalid_since"] is None


async def test_a_collection_type_is_marked_in_its_own_table(client):
    """``tables_for()`` decides which document table a mark is written to, and
    getting that wrong is an ``UPDATE`` of the global table by ids that mean
    something else there (Phase 5 §6.3)."""
    created = (
        await client.post(
            TYPES,
            json={
                "key": "session",
                "label": "Session",
                "collection": "events",
                "fields": [field("name", "text"), field("room", "text")],
                "display_field": "name",
            },
            headers=roles(ADMIN),
        )
    ).json()
    made = await client.post(
        f"{TYPES}/session/records", json={"data": {"name": "Keynote"}}, headers=roles(ADMIN)
    )
    assert made.status_code == 201, made.text
    forced = await client.put(
        f"{TYPES}/session",
        json={
            "expected_version": created["version"],
            "fields": [created["fields"][0], {**created["fields"][1], "required": True}],
            "force": True,
        },
        headers=roles(ADMIN),
    )
    assert forced.status_code == 200, forced.text

    uuid = made.json()["uuid"]
    read = (await client.get(f"{TYPES}/session/records/{uuid}", headers=roles(ADMIN))).json()
    assert read["invalid_since"] is not None
    async with client.db_state.session_factory() as session:
        rtype = (
            await session.execute(select(RecordType).where(RecordType.key == "session"))
        ).scalar_one()
        from sm_records.models import tables_for

        cls = tables_for(rtype).record
        marked = (
            (await session.execute(select(cls.uuid).where(cls.invalid_since.isnot(None))))
            .scalars()
            .all()
        )
        assert marked == [uuid]
        # The global table knows nothing about it.
        assert (
            await session.execute(select(Record.uuid).where(Record.invalid_since.isnot(None)))
        ).scalars().all() == []
