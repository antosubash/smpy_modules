"""``--tenant`` on the CLI, and ``records tenants``: tenancy design §A.5, §J, K11.

A CLI process has no request, so nothing binds a tenant for it. Every command
binds ``--tenant`` itself (default ``default``). ``reindex`` and ``verify``
without ``--type`` visit every tenant. Each test runs the real command
functions against a database of their own: the suite's Postgres database when
the suite is pointed at one, and otherwise a SQLite file, since the commands
open their own engine and ``:memory:`` would be a different, empty database.

The fixtures seed through the ORM inside ``tenant_scope``. Each test opts out
of the suite's ``default`` binding, as a CLI process has none. The entry points
that call ``asyncio.run`` themselves (``main``, ``force_pending``) run on a
worker thread with a loop of their own, as they would in a real process.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sm_records.cli import main, reindex, run_verify, seed, tenants
from sm_records.cli_io import export_command, import_command
from sm_records.cli_reindex import force_pending
from sm_records.index._drift import clear_drift
from sm_records.index.reduce import register_reduce_provider
from sm_records.models import Base, IndexReduce, Record, RecordType
from sm_records.services import types as type_service
from sm_records.settings import RecordsSettings
from sm_records.tenancy import install_guard, tenant_scope
from sqlalchemy import select, update

from tests.app_harness import seed_record, seed_type
from tests.pg_support import TEST_URL, USING_POSTGRES, make_db_state
from tests.test_reduce import make, state_spec

pytestmark = pytest.mark.unbound_tenant

FIELDS = [
    {"key": "name", "type": "text", "label": "Name", "indexed": True},
    {"key": "price", "type": "number", "label": "Price", "indexed": True},
]
STALE = {"price": "2020-01-01T00:00:00+00:00"}


@pytest.fixture
async def cli_db(tmp_path):
    """``(url, db_state)``: the URL a command opens, and a guarded state to seed
    and inspect through."""
    if USING_POSTGRES:
        state, url = await make_db_state(), TEST_URL
    else:
        url = f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}"
        state = init_db(url)
        register_listeners(state)
        async with state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    install_guard(state.sync_session_class)
    clear_drift()
    yield url, state
    clear_drift()
    await state.engine.dispose()


async def _widgets(state: Any, tenant: str, names: list[str], **type_cols: Any) -> RecordType:
    with tenant_scope(tenant):
        rtype = await seed_type(state, "widget", FIELDS, **type_cols)
        for index, name in enumerate(names):
            await seed_record(state, rtype, {"name": name, "price": index})
        return rtype


async def _records(state: Any, tenant: str) -> list[tuple[str, str]]:
    """``(uuid, name)`` of ``tenant``'s widgets, in id order."""
    with tenant_scope(tenant):
        async with state.session_factory() as session:
            rows = (await session.execute(select(Record).order_by(Record.id))).scalars().all()
            return [(row.uuid, row.data["name"]) for row in rows]


async def _main(*argv: str) -> int:
    return await asyncio.to_thread(main, list(argv))


async def _pending(state: Any, tenant: str) -> dict:
    with tenant_scope(tenant):
        async with state.session_factory() as session:
            rtype = (await session.execute(select(RecordType))).scalars().one()
            return dict(rtype.reindex_pending or {})


async def test_export_reads_one_tenant_and_import_writes_into_another(cli_db, tmp_path):
    url, state = cli_db
    await _widgets(state, "default", ["Home 0", "Home 1"])
    await _widgets(state, "acme", ["Acme 0", "Acme 1", "Acme 2"])
    await _widgets(state, "globex", [])
    out = tmp_path / "acme.json"

    await export_command(url, "widget", "json", str(out), tenant="acme")
    exported = json.loads(out.read_text())["records"]
    assert [row["data"]["name"] for row in exported] == ["Acme 0", "Acme 1", "Acme 2"]

    report = await import_command(
        url,
        "widget",
        str(out),
        mode="upsert",
        on_error="abort",
        match_by="uuid",
        force=False,
        apply=True,
        tenant="globex",
    )
    assert report.created == 3
    # The same uuids, now in two tenants: uuids are unique per tenant (§C).
    assert await _records(state, "globex") == await _records(state, "acme")
    assert [name for _, name in await _records(state, "default")] == ["Home 0", "Home 1"]


async def test_seed_reset_only_sees_its_own_tenant(cli_db):
    url, _state = cli_db
    home = await seed(url, records=10, seed_value=1, reset=False, tenant="default")
    await seed(url, records=10, seed_value=1, reset=False, tenant="acme")
    again = await seed(url, records=10, seed_value=2, reset=True, tenant="acme")

    counts = await tenants(url)
    assert counts["default"].records == home.total, "acme's reset left default alone"
    assert counts["acme"].records == again.total, "the reset emptied acme first"
    assert counts["acme"].types == counts["default"].types


async def test_reindex_type_runs_in_one_tenant_and_the_bare_command_in_all(cli_db, capsys):
    url, state = cli_db
    await _widgets(state, "default", ["Home"], reindex_pending=STALE)
    await _widgets(state, "acme", ["Acme"], reindex_pending=STALE)

    await asyncio.to_thread(force_pending, url, "widget", "acme")
    assert await reindex(url, "widget", "acme") == 1
    assert "acme/widget — 1 record(s)" in capsys.readouterr().out
    assert await _pending(state, "acme") == {}
    assert await _pending(state, "default") == STALE, "--tenant acme left default pending"

    assert await reindex(url, None) == 1
    assert "default/widget — 1 record(s)" in capsys.readouterr().out
    assert await _pending(state, "default") == {}

    with pytest.raises(SystemExit, match="in tenant 'globex'"):
        await reindex(url, "widget", "globex")


async def test_reindex_with_tenant_and_no_type_narrows_to_that_tenant(cli_db, capsys):
    url, state = cli_db
    await _widgets(state, "default", ["Home"], reindex_pending=STALE)
    await _widgets(state, "acme", ["Acme"], reindex_pending=STALE)

    assert await _main("reindex", "--database-url", url, "--tenant", "acme") == 0
    assert "acme/widget" in capsys.readouterr().out
    assert await _pending(state, "default") == STALE


async def _orders(state: Any, tenant: str, settings: RecordsSettings) -> int:
    fields = [
        {"key": key, "type": kind, "label": key.title(), "indexed": True}
        for key, kind in (("state", "text"), ("total", "number"), ("name", "text"))
    ]
    with tenant_scope(tenant):
        async with state.session_factory() as session:
            rtype = await type_service.create_type(
                session, key="order", label="Order", fields_raw=fields, settings=settings
            )
            await make(session, rtype, settings, "CA", 10)
            await session.commit()
            return int(rtype.id)


async def test_verify_checks_each_tenant_in_its_own_scope(cli_db, capsys):
    url, state = cli_db
    settings = RecordsSettings()
    register_reduce_provider(state_spec())
    await _orders(state, "default", settings)
    acme = await _orders(state, "acme", settings)

    assert await run_verify(url, None) == 0
    assert "clean across 2 type(s)" in capsys.readouterr().out

    # IndexReduce has no tenant column: it is scoped by its type id.
    async with state.session_factory() as session:
        stmt = update(IndexReduce).where(IndexReduce.type_id == acme).values(count=9)
        await session.execute(stmt)
        await session.commit()

    assert await run_verify(url, None) == 1
    assert "DRIFT acme/order/" in capsys.readouterr().out
    assert await run_verify(url, None, "default") == 0
    assert await run_verify(url, "order", "acme") == 1


async def test_tenants_lists_every_tenant_with_its_counts(cli_db, capsys):
    url, state = cli_db
    await _widgets(state, "default", ["Home 0", "Home 1"])
    acme = await _widgets(state, "acme", ["Acme"])
    with tenant_scope("acme"):
        await seed_record(state, acme, {"name": "gone"}, is_deleted=True)

    assert await _main("tenants", "--database-url", url) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["tenant", "types", "records", "trashed"]
    assert [line.split() for line in lines[1:]] == [
        ["acme", "1", "1", "1"],
        ["default", "1", "2", "0"],
    ]


def test_a_malformed_tenant_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as refused:
        main(["export", "--type", "widget", "--tenant", "no spaces"])
    assert refused.value.code == 2
    assert "not a valid tenant id" in capsys.readouterr().err
