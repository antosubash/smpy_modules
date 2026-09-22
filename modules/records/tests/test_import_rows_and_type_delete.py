"""MINOR 5: bounding the import, and deleting a type set-based.

Two synchronous handlers that grew with the type rather than with the request.
A 10,000-row import ran 44 s and `DELETE /types/{key}` on the same type ran
101 s, both inside one HTTP request and both past nginx's default 60 s
`proxy_read_timeout` — at which point the client sees a 504 while the server
keeps going. `max_import_bytes` permitted roughly 1.7 M rows, so the
*documented* ceiling was hours.

So: `max_import_rows` refuses a file that is more work than one request will
do, before anything is written, and the type delete stopped being per-record.

Measured on `ci_collate` with a 10,000-row seed:

* delete: 101.6 s -> 0.4 s
* import: unchanged (43.7 s); the ceiling bounds it rather than speeding it up,
  which is the whole point of a ceiling.
"""

from __future__ import annotations

import json

from sqlalchemy import func, select

from tests.app_harness import ADMIN, roles

_API = "/api/records/types"
_FIELDS = [
    {"key": "name", "type": "text", "label": "Name", "indexed": True},
    {"key": "count", "type": "integer", "label": "Count", "indexed": True},
]


async def _type(client, key: str) -> dict:
    resp = await client.post(
        _API,
        json={"key": key, "label": key.title(), "fields": _FIELDS, "display_field": "name"},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _settings(client):
    return client.app.state.sm_records.settings


def _csv(rows: int) -> bytes:
    header = "uuid,slug,locale,translation_group,status,position,name,count"
    body = [f",,,,draft,0,row-{index},{index}" for index in range(rows)]
    return "\r\n".join([header, *body]).encode()


def _json(rows: int) -> bytes:
    return json.dumps(
        {"records": [{"data": {"name": f"row-{index}", "count": index}} for index in range(rows)]}
    ).encode()


async def _import(client, key: str, payload: bytes, fmt: str, **params):
    query = "&".join(f"{name}={value}" for name, value in params.items())
    return await client.post(
        f"{_API}/{key}/records/import?format={fmt}&{query}",
        content=payload,
        headers={
            **roles(ADMIN),
            "Content-Type": "text/csv" if fmt == "csv" else "application/json",
        },
    )


# --- max_import_rows -------------------------------------------------------


async def test_a_json_file_over_the_row_ceiling_is_a_413(client):
    _settings(client).max_import_rows = 5
    await _type(client, "rowsjson")
    resp = await _import(client, "rowsjson", _json(6), "json", dry_run="false")
    assert resp.status_code == 413, resp.text
    assert "5-row limit" in resp.json()["detail"]


async def test_a_csv_file_over_the_row_ceiling_is_a_413(client):
    _settings(client).max_import_rows = 5
    await _type(client, "rowscsv")
    resp = await _import(client, "rowscsv", _csv(6), "csv", dry_run="false")
    assert resp.status_code == 413, resp.text
    assert "5-row limit" in resp.json()["detail"]


async def test_the_ceiling_is_exact_and_nothing_is_written_over_it(client):
    _settings(client).max_import_rows = 5
    await _type(client, "rowsedge")
    at_limit = await _import(client, "rowsedge", _csv(5), "csv", dry_run="false")
    assert at_limit.status_code == 200, at_limit.text
    assert at_limit.json()["created"] == 5

    over = await _import(client, "rowsedge", _csv(6), "csv", dry_run="false")
    assert over.status_code == 413, over.text
    listed = await client.get(f"{_API}/rowsedge/records", headers=roles(ADMIN))
    assert listed.json()["total"] == 5, "the refused file wrote rows anyway"


async def test_a_dry_run_is_refused_too(client):
    """A dry run validates every row, which is the work being bounded."""
    _settings(client).max_import_rows = 5
    await _type(client, "rowsdry")
    resp = await _import(client, "rowsdry", _csv(6), "csv", dry_run="true")
    assert resp.status_code == 413, resp.text


async def test_the_default_ceiling_lets_an_ordinary_file_through(client):
    await _type(client, "rowsdefault")
    assert _settings(client).max_import_rows == 20000
    resp = await _import(client, "rowsdefault", _csv(50), "csv", dry_run="false")
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 50


# --- the set-based type delete --------------------------------------------


async def _index_rows(client, type_id: int) -> int:
    from sm_records.models import GLOBAL

    total = 0
    async with client.db_state.session_factory() as session:
        for table in GLOBAL.index_tables:
            stmt = select(func.count()).select_from(table).where(table.type_id == type_id)
            total += int((await session.execute(stmt)).scalar_one())
    return total


async def test_deleting_a_type_removes_documents_revisions_and_index_rows(client):
    await _type(client, "purgeme")
    resp = await _import(client, "purgeme", _csv(40), "csv", dry_run="false")
    assert resp.status_code == 200, resp.text
    listed = await client.get(f"{_API}/purgeme/records", headers=roles(ADMIN))
    assert listed.json()["total"] == 40

    async with client.db_state.session_factory() as session:
        from sm_records.models import RecordType

        type_id = int(
            (
                await session.execute(select(RecordType.id).where(RecordType.key == "purgeme"))
            ).scalar_one()
        )
    assert await _index_rows(client, type_id) > 0

    deleted = await client.delete(
        f"{_API}/purgeme", params={"confirm_record_count": 40}, headers=roles(ADMIN)
    )
    assert deleted.status_code == 204, deleted.text
    assert await _index_rows(client, type_id) == 0

    from sm_records.models import GLOBAL

    async with client.db_state.session_factory() as session:
        docs = (
            await session.execute(
                select(func.count())
                .select_from(GLOBAL.record)
                .where(GLOBAL.record.type_id == type_id)
                .execution_options(include_deleted=True)
            )
        ).scalar_one()
        revisions = (
            await session.execute(
                select(func.count())
                .select_from(GLOBAL.revision)
                .where(
                    GLOBAL.revision.record_id.in_(
                        select(GLOBAL.record.id).where(GLOBAL.record.type_id == type_id)
                    )
                )
            )
        ).scalar_one()
    assert (docs, revisions) == (0, 0)


async def test_the_trash_goes_with_the_type(client):
    """The delete purges live records *and* the trash, and the confirmation
    counts both — a set-based delete must not quietly drop the soft-deleted
    half by inheriting the ORM's filter."""
    await _type(client, "purgetrash")
    created = await client.post(
        f"{_API}/purgetrash/records", json={"data": {"name": "a"}}, headers=roles(ADMIN)
    )
    assert created.status_code == 201, created.text
    trashed = await client.delete(
        f"{_API}/purgetrash/records/{created.json()['uuid']}", headers=roles(ADMIN)
    )
    assert trashed.status_code in (200, 204), trashed.text

    from sm_records.contracts.events import RecordPurged
    from sm_records.models import GLOBAL

    from tests.events_harness import recorder

    seen = recorder(client)
    resp = await client.delete(
        f"{_API}/purgetrash", params={"confirm_record_count": 1}, headers=roles(ADMIN)
    )
    assert resp.status_code == 204, resp.text
    # The row is gone, and the event names it: the column select the purge
    # reads its events from carries ``include_deleted``, so a trashed record
    # is purged *and* reported rather than silently dropped by the ORM's
    # soft-delete filter.
    assert [event.uuid for event in seen.only(RecordPurged)] == [created.json()["uuid"]]
    async with client.db_state.session_factory() as session:
        left = (
            await session.execute(
                select(func.count())
                .select_from(GLOBAL.record)
                .where(GLOBAL.record.uuid == created.json()["uuid"])
                .execution_options(include_deleted=True)
            )
        ).scalar_one()
    assert left == 0


async def test_the_purge_events_still_name_every_record(client):
    """Set-based or not, a subscriber gets one `RecordPurged` per record and
    then the `RecordTypeDeleted` — identity only, which is what the docs now
    promise."""
    from sm_records.contracts.events import RecordPurged, RecordTypeDeleted

    from tests.events_harness import recorder

    await _type(client, "purgeevents")
    imported = await _import(client, "purgeevents", _csv(3), "csv", dry_run="false")
    assert imported.status_code == 200, imported.text

    seen = recorder(client)
    resp = await client.delete(
        f"{_API}/purgeevents", params={"confirm_record_count": 3}, headers=roles(ADMIN)
    )
    assert resp.status_code == 204, resp.text

    purged = seen.only(RecordPurged)
    deleted = seen.only(RecordTypeDeleted)
    assert len(purged) == 3
    assert {event.type_key for event in purged} == {"purgeevents"}
    assert all(event.uuid and event.locale and event.translation_group for event in purged)
    assert len(deleted) == 1 and deleted[0].purged == 3
    # The records first, so a subscriber that drops its own rows per record and
    # then forgets the type sees them in that order.
    assert seen.seen.index(deleted[0]) > max(seen.seen.index(event) for event in purged)
