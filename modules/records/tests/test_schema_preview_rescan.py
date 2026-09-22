"""``rescan=true`` — "which records does the schema refuse *now*".

After a forced restrictive change the operator has a worklist: the records the
scan named as failing. There was no way to ask for it again. Re-previewing the
stored fields produces an empty diff, ``needs_dry_run`` sees nothing
restrictive in it, and ``change_report`` short-circuits to ``checked=N,
failing=0`` — which reads as "everything is fine" and means "nothing was
checked". ``SchemaPreviewPanel.tsx`` shipped an apology in place of the answer.

``rescan`` forces the scan whatever the diff says, and is the whole feature.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, roles

TYPES = "/api/records/types"


def _field(key: str, type_: str, *, required: bool = False, **options) -> dict:
    return {
        "key": key,
        "type": type_,
        "label": key.title(),
        "required": required,
        "unique": False,
        "indexed": True,
        "default": None,
        "help": None,
        "constraints": {},
        "options": options,
    }


async def _forced_break(client) -> dict:
    """A type with one record, then ``sku`` forced ``required`` over it — the
    state that produces a worklist and no way to read it back."""
    created = (
        await client.post(
            TYPES,
            json={
                "key": "product",
                "label": "Product",
                "fields": [_field("name", "text"), _field("sku", "text")],
                "display_field": "name",
            },
            headers=roles(ADMIN),
        )
    ).json()
    record = await client.post(
        f"{TYPES}/product/records", json={"data": {"name": "Widget"}}, headers=roles(ADMIN)
    )
    assert record.status_code == 201, record.text

    required_sku = {**created["fields"][1], "required": True}
    forced = await client.put(
        f"{TYPES}/product",
        json={
            "expected_version": created["version"],
            "fields": [created["fields"][0], required_sku],
            "force": True,
        },
        headers=roles(ADMIN),
    )
    assert forced.status_code == 200, forced.text
    return {"type": forced.json(), "uuid": record.json()["uuid"]}


async def test_without_rescan_an_empty_diff_reports_nothing_checked_as_nothing_wrong(client):
    """The behaviour that made the flag necessary, pinned so the short circuit
    is not mistaken for a bug later: with no diff there is nothing a change
    could break, and that is a correct answer to a different question."""
    state = await _forced_break(client)
    resp = await client.post(
        f"{TYPES}/product/schema/preview",
        json={"fields": state["type"]["fields"]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["changes"] == []
    assert body["report"]["checked"] == 1
    assert body["report"]["failing"] == 0
    assert body["report"]["sample"] == []


async def test_rescan_scans_the_stored_schema_and_names_the_failing_records(client):
    state = await _forced_break(client)
    resp = await client.post(
        f"{TYPES}/product/schema/preview",
        json={"fields": state["type"]["fields"], "rescan": True},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["changes"] == []
    assert body["kind"] == "additive"
    report = body["report"]
    assert report["checked"] == 1
    assert report["failing"] == 1
    assert report["clean"] is False
    assert [entry["uuid"] for entry in report["sample"]] == [state["uuid"]]
    assert report["sample"][0]["errors"][0]["field"] == "sku"


async def test_rescan_on_a_healthy_type_is_clean(client):
    """It is a question, not an assertion of breakage: a type nothing is wrong
    with answers ``failing: 0`` after a real scan, which is a different
    statement from the short circuit above and has to be distinguishable only
    by having happened."""
    state = await _forced_break(client)
    fixed = await client.put(
        f"{TYPES}/product/records/{state['uuid']}",
        json={"expected_version": 1, "data": {"name": "Widget", "sku": "W-1"}},
        headers=roles(ADMIN),
    )
    assert fixed.status_code == 200, fixed.text

    resp = await client.post(
        f"{TYPES}/product/schema/preview",
        json={"fields": state["type"]["fields"], "rescan": True},
        headers=roles(ADMIN),
    )
    assert resp.json()["report"] == {
        "checked": 1,
        "failing": 0,
        "sample": [],
        "orphaned_conflicts": {},
        "duplicates": {},
        "clean": True,
    }


async def test_a_rescan_report_is_never_reused_by_a_save(client):
    """``_preview.reused_report`` keys a finished job's report on the proposed
    fields, and "Check records" sends the stored ones — so without ``rescan``
    in the signature a save of the same list would inherit a ``failing`` count
    about records the change does not touch and be refused."""
    from sm_records.services.preview_jobs import fields_hash

    fields = [_field("name", "text")]
    assert fields_hash(fields, None, None, rescan=True) != fields_hash(fields, None, None)
