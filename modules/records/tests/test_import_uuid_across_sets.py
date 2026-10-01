"""The importer may not create a record under a uuid another table set holds.

The half of Phase 5 §6.4 that is about the *data* rather than about the
lookups (``test_collision_uuid_sets.py`` is the other half). §2 has the
importer keep a file's uuid verbatim so a round trip is idempotent, which made
"export a global type, import it into a collection type" — the §12 motivation
for collections in the first place — plant a duplicate every time.

It is a **row** error, raised in the planning pass, so all four of the
importer's shapes agree about it: a dry run predicts it, ``abort`` refuses the
whole file before writing anything, ``skip`` reports the row and imports the
rest, and the message names where the uuid is already in use.
"""

from __future__ import annotations

import json

import pytest_asyncio

from tests.app_harness import ADMIN, roles
from tests.collections_harness import EVENTS  # noqa: F401 - declares at import
from tests.io_helpers import field, make_record, make_type, post_import

API = "/api/records/types"


def _rows(*rows: dict) -> str:
    return json.dumps({"records": list(rows)})


@pytest_asyncio.fixture
async def two_sets(client):
    """A global ``glob`` type and a ``gig`` type in the ``events`` collection."""
    await make_type(client, "glob", [field("name", "text", indexed=True)], display_field="name")
    await make_type(
        client,
        "gig",
        [field("name", "text", indexed=True)],
        display_field="name",
        collection="events",
    )
    return client


async def test_a_global_records_uuid_cannot_be_imported_into_a_collection(two_sets, client):
    kept = await make_record(client, "glob", {"name": "Barbican"})
    refused = await post_import(
        client, "gig", _rows({"uuid": kept["uuid"], "data": {"name": "Clash"}}), dry_run="false"
    )
    assert refused.status_code == 422, refused.text
    body = refused.json()["report"]
    assert body["created"] == 0
    assert body["errors"][0]["row"] == 1
    assert "already exists in the global set" in body["errors"][0]["message"]


async def test_a_collection_records_uuid_cannot_be_imported_into_the_global_set(two_sets, client):
    """The message names the *collection* when that is where the uuid lives."""
    made = await post_import(client, "gig", _rows({"data": {"name": "Clash"}}), dry_run="false")
    assert made.status_code == 200, made.text
    listed = await client.get(f"{API}/gig/records", headers=roles(ADMIN))
    taken = listed.json()["items"][0]["uuid"]

    refused = await post_import(
        client, "glob", _rows({"uuid": taken, "data": {"name": "Other"}}), dry_run="false"
    )
    assert refused.status_code == 422, refused.text
    assert "already exists in collection 'events'" in refused.text


async def test_the_dry_run_predicts_the_refusal(two_sets, client):
    kept = await make_record(client, "glob", {"name": "Barbican"})
    preview = await post_import(
        client, "gig", _rows({"uuid": kept["uuid"], "data": {"name": "Clash"}}), dry_run="true"
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["created"] == 0
    assert preview.json()["failed"] == 1
    assert "already exists in the global set" in preview.json()["errors"][0]["message"]


async def test_skip_mode_reports_the_row_and_imports_the_rest(two_sets, client):
    kept = await make_record(client, "glob", {"name": "Barbican"})
    report = await post_import(
        client,
        "gig",
        _rows(
            {"uuid": kept["uuid"], "data": {"name": "Clash"}},
            {"uuid": "b" * 32, "data": {"name": "Fine"}},
        ),
        dry_run="false",
        on_error="skip",
    )
    assert report.status_code == 200, report.text
    assert report.json()["created"] == 1
    assert report.json()["failed"] == 1
    assert report.json()["errors"][0]["row"] == 1


async def test_a_trashed_record_still_owns_its_uuid(two_sets, client):
    """A trashed row keeps its claim until it is purged, exactly as it keeps
    its slug — otherwise a restore would find its identity taken."""
    kept = await make_record(client, "glob", {"name": "Barbican"})
    binned = await client.delete(f"{API}/glob/records/{kept['uuid']}", headers=roles(ADMIN))
    assert binned.status_code == 204, binned.text

    refused = await post_import(
        client, "gig", _rows({"uuid": kept["uuid"], "data": {"name": "Clash"}}), dry_run="false"
    )
    assert refused.status_code == 422, refused.text
    assert "already exists in the global set" in refused.text


async def test_purge_then_import_is_the_supported_move(two_sets, client):
    """The README's sequence: export, delete the type (which purges), import.

    Doing it the other way round is what the refusal above is about, so this
    is the test that the supported path still works end to end.
    """
    kept = await make_record(client, "glob", {"name": "Barbican"})
    dropped = await client.delete(f"{API}/glob?confirm_record_count=1", headers=roles(ADMIN))
    assert dropped.status_code == 204, dropped.text

    moved = await post_import(
        client, "gig", _rows({"uuid": kept["uuid"], "data": {"name": "Barbican"}}), dry_run="false"
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["created"] == 1
    read = await client.get(f"{API}/gig/records/{kept['uuid']}", headers=roles(ADMIN))
    assert read.status_code == 200, read.text


async def test_a_round_trip_inside_one_set_is_untouched(two_sets, client):
    """The check skips the type's **own** table set, so re-importing a type's
    own export still matches and skips rather than being refused."""
    made = await make_record(client, "gig", {"name": "Clash"})
    export = await client.get(f"{API}/gig/records/export?format=json", headers=roles(ADMIN))
    again = await post_import(client, "gig", export.text, dry_run="false")
    assert again.status_code == 200, again.text
    assert again.json()["skipped"] == 1
    assert again.json()["failed"] == 0
    assert made["uuid"] in export.text
