"""``python -m sm_records.cli export`` / ``import``, run against a real file.

Against a file-backed SQLite database rather than the ``:memory:`` one the
rest of the suite uses, because the thing under test is the part the HTTP
tests cannot reach: the CLI owns its own connection and is the one caller in
this module allowed to ``commit`` (``CLAUDE.md`` reserves that for the
framework's session everywhere else). A dry run that quietly committed, or an
``--apply`` that quietly did not, is invisible without a second connection to
check from.
"""

from __future__ import annotations

import json

import pytest
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sm_records.cli_io import export_command, import_command
from sm_records.models import Base, Record, RecordType
from sm_records.services.records import create_record
from sm_records.settings import RecordsSettings
from sqlalchemy import select

FIELDS = [
    {"key": "name", "type": "text", "label": "Name", "indexed": True},
    {"key": "price", "type": "number", "label": "Price"},
]


@pytest.fixture
async def catalogue_db(tmp_path):
    """A ``widget`` type with three records, in a file this test can reopen."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}"
    state = init_db(url)
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with state.session_factory() as session:
        rtype = RecordType(
            key="widget", label="Widget", label_plural="Widgets", fields=FIELDS, schema_version=1
        )
        session.add(rtype)
        await session.flush()
        for index in range(3):
            await create_record(
                session,
                rtype,
                data={"name": f"Widget {index}", "price": f"{index}.50"},
                settings=RecordsSettings(),
            )
        await session.commit()
    await state.engine.dispose()
    return url


async def _records(url: str) -> list[Record]:
    state = init_db(url)
    register_listeners(state)
    try:
        async with state.session_factory() as session:
            rows = (await session.execute(select(Record).order_by(Record.id))).scalars().all()
            return [
                Record(uuid=r.uuid, data=dict(r.data), version=r.version, type_id=r.type_id)
                for r in rows
            ]
    finally:
        await state.engine.dispose()


async def test_export_json_then_import_is_a_no_op(catalogue_db, tmp_path):
    out = tmp_path / "widgets.json"
    written = await export_command(catalogue_db, "widget", "json", str(out))
    assert written == len(out.read_text(encoding="utf-8"))

    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["type"]["key"] == "widget"
    assert len(document["records"]) == 3

    before = {r.uuid: r.version for r in await _records(catalogue_db)}
    report = await import_command(
        catalogue_db,
        "widget",
        str(out),
        mode="upsert",
        on_error="abort",
        match_by="uuid",
        force=False,
        apply=True,
    )
    assert (report.created, report.updated, report.skipped) == (0, 0, 3)
    assert {r.uuid: r.version for r in await _records(catalogue_db)} == before


async def test_export_csv_then_import_is_a_no_op(catalogue_db, tmp_path):
    out = tmp_path / "widgets.csv"
    await export_command(catalogue_db, "widget", "csv", str(out))
    # ``read_bytes`` and not ``read_text``: universal-newline translation
    # would rewrite the RFC 4180 ``\r\n`` this test is checking for.
    table = out.read_bytes().decode("utf-8")
    assert table.split("\r\n")[0] == (
        "uuid,slug,locale,translation_group,status,position,published_at,name,price"
    )

    report = await import_command(
        catalogue_db,
        "widget",
        str(out),
        mode="upsert",
        on_error="abort",
        match_by="uuid",
        force=False,
        apply=True,
    )
    assert (report.created, report.updated, report.skipped) == (0, 0, 3)


async def test_a_dry_run_writes_nothing(catalogue_db, tmp_path):
    out = tmp_path / "widgets.json"
    await export_command(catalogue_db, "widget", "json", str(out))
    document = json.loads(out.read_text(encoding="utf-8"))
    document["records"].append({"data": {"name": "Fourth", "price": "9.99"}})
    out.write_text(json.dumps(document), encoding="utf-8")

    report = await import_command(
        catalogue_db,
        "widget",
        str(out),
        mode="upsert",
        on_error="abort",
        match_by="uuid",
        force=False,
        apply=False,
    )
    assert report.dry_run is True
    assert report.created == 1
    assert len(await _records(catalogue_db)) == 3

    applied = await import_command(
        catalogue_db,
        "widget",
        str(out),
        mode="upsert",
        on_error="abort",
        match_by="uuid",
        force=False,
        apply=True,
    )
    assert applied.created == 1
    assert len(await _records(catalogue_db)) == 4


async def test_a_refused_import_exits_nonzero_and_writes_nothing(catalogue_db, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"records": [{"data": {"name": "Ok"}}, {"data": {"nope": 1}}]}))

    with pytest.raises(SystemExit) as exit_info:
        await import_command(
            catalogue_db,
            "widget",
            str(bad),
            mode="upsert",
            on_error="abort",
            match_by="uuid",
            force=False,
            apply=True,
        )
    assert exit_info.value.code == 1
    assert len(await _records(catalogue_db)) == 3


async def test_export_to_stdout(catalogue_db, capsys):
    written = await export_command(catalogue_db, "widget", "json", None)
    # The document is written as one unbroken stream with no trailing
    # newline, so it is whatever follows the last one — ``_load_settings``
    # prints a line first on a database with no settings tables, which is
    # every scratch database an operator exports from.
    payload = capsys.readouterr().out.rsplit("\n", 1)[-1]
    assert written == len(payload)
    assert json.loads(payload)["type"]["key"] == "widget"
