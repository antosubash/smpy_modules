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
from tests.invalid_support import clear_mark

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


async def test_rescan_with_the_stored_fields_writes_the_mark(client):
    """The half of ``rescan`` that is not a report: rule 1 of the stored mark
    is that a scan of the schema records are *stored against* writes it."""
    state = await _forced_break(client)
    await clear_mark(client, state["uuid"])

    resp = await client.post(
        f"{TYPES}/product/schema/preview",
        json={"fields": state["type"]["fields"], "rescan": True},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    read = await client.get(f"{TYPES}/product/records/{state['uuid']}", headers=roles(ADMIN))
    assert read.json()["invalid_since"] is not None


async def test_rescan_with_fields_that_are_not_the_stored_ones_is_refused(client):
    """The other half of rule 1, and the reason this is a refusal rather than
    a silent correction: ``rescan`` *writes*, so a body whose ``fields`` are a
    proposal would persist a worklist for a schema nobody applied — a badge in
    the editor, a count in the hub and a degraded health check, all derived
    from a field list that exists only in that request. The shipped panel
    sends the stored fields; nothing made that a rule until now.
    """
    state = await _forced_break(client)
    await clear_mark(client, state["uuid"])
    stored = state["type"]["fields"]
    proposed = [stored[0], {**stored[1], "required": False}]

    resp = await client.post(
        f"{TYPES}/product/schema/preview",
        json={"fields": proposed, "rescan": True},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, (resp.status_code, resp.text)
    assert resp.json()["errors"] == [
        {"field": "fields", "message": "does not match the stored schema"}
    ]
    # Refused *before* the scan, so nothing was marked ...
    read = await client.get(f"{TYPES}/product/records/{state['uuid']}", headers=roles(ADMIN))
    assert read.json()["invalid_since"] is None
    # ... and the type is untouched, as it would be after any preview.
    current = (await client.get(f"{TYPES}/product", headers=roles(ADMIN))).json()
    assert [f["required"] for f in current["fields"] if f["key"] == "sku"] == [True]


async def test_the_same_fields_in_any_normal_spelling_are_still_the_stored_ones(client):
    """The comparison is of *normalised definitions*, not of raw JSON: the
    editor round-trips a field list through a form, and a refusal because a
    default came back spelled out would make the button unusable."""
    state = await _forced_break(client)
    loose = [
        {key: value for key, value in field.items() if key not in {"help", "constraints"}}
        for field in state["type"]["fields"]
    ]

    resp = await client.post(
        f"{TYPES}/product/schema/preview",
        json={"fields": loose, "rescan": True},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["report"]["failing"] == 1


def test_the_type_editor_still_sends_the_stored_fields():
    """The server refuses anything else now, so the panel's "Check records"
    branch has to keep sending ``saved.*``. Read from the source rather than
    trusted, for the reason ``test_reserved_keys_sync`` reads ``rules.ts``:
    the two halves of one contract live in two languages."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "sm_records"
        / "components"
        / "typeeditor"
        / "SchemaPreviewPanel.tsx"
    ).read_text(encoding="utf-8")
    call = source[source.index("const runPreview") : source.index("rescan: true,")]
    assert "fields: saved.fields," in call, call[-400:]
