"""Import semantics: the dry run, atomicity, the refusals, and idempotency.

Mode selection and ``match_by`` live next door in ``test_import_modes.py``,
for the 300-line cap; the seam is "what an import does to the database" here
and "which record a row is about" there.
"""

from __future__ import annotations

from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, roles
from tests.io_helpers import (
    PRODUCT,
    catalogue,
    data_by_uuid,
    export_text,
    field,
    make_record,
    make_type,
    parse_rows,
    post_import,
    to_document,
)


async def test_dry_run_is_the_default_and_writes_nothing(client):
    await catalogue(client, products=2)
    rows = parse_rows(await export_text(client, PRODUCT))
    rows.append(
        {
            **rows[0],
            "uuid": None,
            "slug": "brand-new",
            "data": {**rows[0]["data"], "name": "Brand New"},
        }
    )

    before = await data_by_uuid(client, PRODUCT)
    resp = await post_import(client, PRODUCT, to_document(rows))
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["dry_run"] is True
    assert report["total"] == 3
    assert report["created"] == 1
    assert report["skipped"] == 2
    assert await data_by_uuid(client, PRODUCT) == before


async def test_reimporting_an_export_changes_nothing(client):
    await catalogue(client, products=3)
    document = await export_text(client, PRODUCT)
    before = await data_by_uuid(client, PRODUCT)

    first = await post_import(client, PRODUCT, document, dry_run="false")
    assert first.status_code == 200, first.text
    assert first.json()["skipped"] == 3
    assert first.json()["created"] == 0
    assert first.json()["updated"] == 0

    second = await post_import(client, PRODUCT, document, dry_run="false")
    assert second.json()["skipped"] == 3

    after = await data_by_uuid(client, PRODUCT)
    assert {uuid: item["version"] for uuid, item in after.items()} == {
        uuid: item["version"] for uuid, item in before.items()
    }


async def test_abort_is_all_or_nothing(client):
    """A bad row 500 rows in leaves zero writes — the whole file is validated
    before the first ``INSERT``, and the refusal rolls the request back."""
    await make_type(client, PRODUCT, [field("name", "text", required=True, indexed=True)])
    rows = [{"data": {"name": f"Widget {index}"}} for index in range(500)]
    rows.append({"data": {"name": None}})

    resp = await post_import(client, PRODUCT, to_document(rows), dry_run="false")
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["report"]["failed"] == 1
    assert body["report"]["created"] == 0
    assert body["report"]["errors"][0]["row"] == 501
    assert await data_by_uuid(client, PRODUCT) == {}


async def test_abort_stops_at_the_first_bad_row(client):
    """``on_error=abort`` refuses as soon as the answer is settled — S4.

    Nothing is going to be written, so validating the remaining rows only
    decides how long the refusal takes; on a 9,000-row file that was half the
    11 seconds it took to say no. The report therefore names **one** row, the
    first, and ``failed`` is 1 rather than 3.

    The dry run below is the other half of the contract and the reason this is
    an acceptable trade: a caller who wants the whole list of what is wrong
    with the file asks for the preview that exists to produce it, and gets all
    three rows.
    """
    await make_type(client, PRODUCT, [field("name", "text", required=True, indexed=True)])
    rows = [
        {"data": {"name": "Good"}},
        {"data": {"name": None}},
        {"data": {"name": None}},
        {"data": {"name": None}},
    ]

    refused = await post_import(client, PRODUCT, to_document(rows), dry_run="false")
    assert refused.status_code == 422, refused.text
    report = refused.json()["report"]
    assert report["failed"] == 1, "abort should stop at the row that settles it"
    assert [error["row"] for error in report["errors"]] == [2]
    assert report["total"] == 4, "the file's size is still what it is"
    assert await data_by_uuid(client, PRODUCT) == {}

    preview = await post_import(client, PRODUCT, to_document(rows))
    assert preview.status_code == 200, preview.text
    assert preview.json()["failed"] == 3, "a dry run still reports every bad row"


async def test_skip_still_reports_every_bad_row(client):
    """``skip`` cannot short-circuit: every row that is fine is still going to
    be written, so every row that is not still has to be reported."""
    await make_type(client, PRODUCT, [field("name", "text", required=True, indexed=True)])
    rows = [
        {"data": {"name": None}},
        {"data": {"name": "Good"}},
        {"data": {"name": None}},
    ]
    resp = await post_import(client, PRODUCT, to_document(rows), dry_run="false", on_error="skip")
    assert resp.status_code == 200, resp.text
    assert resp.json()["failed"] == 2
    assert resp.json()["created"] == 1


async def test_skip_writes_the_valid_rows(client):
    await make_type(client, PRODUCT, [field("name", "text", required=True, indexed=True)])
    rows = [
        {"data": {"name": "Good one"}},
        {"data": {"name": None}},
        {"data": {"name": "Good two"}},
    ]

    resp = await post_import(client, PRODUCT, to_document(rows), dry_run="false", on_error="skip")
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert (report["created"], report["failed"], report["total"]) == (2, 1, 3)
    names = sorted(item["data"]["name"] for item in (await data_by_uuid(client, PRODUCT)).values())
    assert names == ["Good one", "Good two"]


async def test_update_without_a_version_is_refused_unless_forced(client):
    await catalogue(client, products=1)
    rows = parse_rows(await export_text(client, PRODUCT))
    rows[0]["data"]["name"] = "Renamed"

    refused = await post_import(client, PRODUCT, to_document(rows), dry_run="false")
    assert refused.status_code == 422, refused.text
    assert "version" in refused.json()["report"]["errors"][0]["message"]

    forced = await post_import(client, PRODUCT, to_document(rows), dry_run="false", force="true")
    assert forced.status_code == 200, forced.text
    assert forced.json()["updated"] == 1
    assert next(iter((await data_by_uuid(client, PRODUCT)).values()))["data"]["name"] == "Renamed"


async def test_a_stale_version_loses_the_race(client):
    await catalogue(client, products=1)
    rows = parse_rows(await export_text(client, PRODUCT))
    rows[0]["version"] = 99
    rows[0]["data"]["name"] = "Renamed"

    resp = await post_import(client, PRODUCT, to_document(rows), dry_run="false")
    assert resp.status_code == 422, resp.text
    assert "has changed since it was read" in resp.json()["report"]["errors"][0]["message"]


async def test_orphaned_is_refused(client):
    await catalogue(client, products=1)
    rows = parse_rows(await export_text(client, PRODUCT))
    rows[0]["data"]["_orphaned"] = {"gone": "value"}

    resp = await post_import(client, PRODUCT, to_document(rows))
    assert resp.status_code == 200, resp.text
    errors = resp.json()["errors"]
    assert errors[0]["field"] == "_orphaned"
    assert "reserved" in errors[0]["message"]


async def test_unknown_field_is_refused(client):
    await catalogue(client, products=1)
    rows = parse_rows(await export_text(client, PRODUCT))
    rows[0]["data"]["nonsense"] = 1

    resp = await post_import(client, PRODUCT, to_document(rows))
    assert resp.json()["failed"] == 1
    assert resp.json()["errors"][0]["field"] == "nonsense"

    header = await export_text(client, PRODUCT, "csv")
    broken = header.replace("name,", "nonsense,", 1)
    csv_resp = await post_import(client, PRODUCT, broken, fmt="csv")
    assert csv_resp.status_code == 400, csv_resp.text
    assert "nonsense" in csv_resp.json()["detail"]


async def test_a_file_over_the_ceiling_is_413(client):
    await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    client.app.state.sm_records.settings = RecordsSettings(max_import_bytes=64)
    rows = [{"data": {"name": "x" * 50}} for _ in range(20)]

    resp = await post_import(client, PRODUCT, to_document(rows), dry_run="false")
    assert resp.status_code == 413, resp.text
    assert "over the 64-byte limit" in resp.json()["detail"]


async def test_malformed_json_names_the_line(client):
    await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    resp = await post_import(client, PRODUCT, '{"records": [ {"data": }] }')
    assert resp.status_code == 400, resp.text
    assert "line 1" in resp.json()["detail"]


async def test_a_short_csv_row_names_the_row(client):
    await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    await make_record(client, PRODUCT, {"name": "Widget"})
    table = await export_text(client, PRODUCT, "csv")
    broken = table + "only,two\r\n"

    resp = await post_import(client, PRODUCT, broken, fmt="csv")
    assert resp.status_code == 200, resp.text
    assert resp.json()["errors"][0]["row"] == 2


async def test_multipart_upload_carries_its_own_options(client):
    await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    resp = await client.post(
        f"/api/records/types/{PRODUCT}/records/import",
        files={
            "file": ("rows.json", to_document([{"data": {"name": "Uploaded"}}]), "application/json")
        },
        data={"dry_run": "false", "mode": "create"},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1
    assert resp.json()["dry_run"] is False


async def test_the_error_list_is_capped_but_the_count_is_not(client):
    """A file that fails every row must not answer with one error per row:
    the list is capped at 200 and ``failed`` stays exact, so the response
    cannot outgrow the file it describes."""
    await make_type(client, PRODUCT, [field("name", "text", required=True, indexed=True)])
    rows = [{"data": {"name": None}} for _ in range(250)]

    resp = await post_import(client, PRODUCT, to_document(rows))
    report = resp.json()
    assert report["total"] == 250
    assert report["failed"] == 250
    assert len(report["errors"]) == 200
    assert report["errors_truncated"] is True
