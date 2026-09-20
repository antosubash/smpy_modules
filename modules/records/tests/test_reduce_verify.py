"""The other two legs of the reduce index: the rebuild, and the verifier.

Design §7.5 refused a maintained aggregate because it is a second source of
truth that can drift. Phase 5 §5.2 builds it anyway and answers the objection
rather than denying it: the table is always **derivable** from the records
(the rebuild), and any disagreement is **detectable** (the verifier, its exit
code, and the health detail it feeds). These tests are that claim.

The concurrency case at the bottom uses the file-backed harness of
``test_unique_concurrency.py`` for the reason that module's docstring gives:
on ``:memory:`` with a ``StaticPool`` every session shares one connection and
one transaction, so a lost increment cannot be caught there at all.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sm_records.deps import require_edit, require_manage_types, require_view
from sm_records.health import stale_reindex_check
from sm_records.index._drift import clear_drift, current_drift
from sm_records.index.reduce import register_reduce_provider
from sm_records.index.reduce_rebuild import rebuild_type, verify_type
from sm_records.index.reindex import reindex_type
from sm_records.models import Base, IndexReduce
from sm_records.services._common import utcnow
from sqlalchemy import delete, select, update

from tests.app_harness import build_app, seed_type
from tests.test_reduce import STATE, make, state_spec, stored

API = "/api/records/types"
WRITERS = 8


@pytest.fixture
def settings():
    from sm_records.settings import RecordsSettings

    return RecordsSettings()


@pytest.fixture
async def order_type(make_type, field_def):
    return await make_type(
        "order",
        [field_def("state", "text"), field_def("total", "number"), field_def("name", "text")],
        display_field="name",
    )


@pytest.fixture(autouse=True)
def _clean_drift():
    clear_drift()
    yield
    clear_drift()


async def test_a_rebuild_reproduces_the_delta_maintained_table(db, order_type, settings):
    """The property the whole design rests on: the stored rows are never more
    than a cache of the records, so throwing them away and recomputing gives
    back exactly what the incremental writes built."""
    spec = state_spec()
    register_reduce_provider(spec)
    for state, total in (("CA", 10), ("CA", 5), ("NY", 2), ("TX", 7)):
        await make(db, order_type, settings, state, total, name=f"{state}{total}")
    incremental = await stored(db, order_type)

    await rebuild_type(db, order_type, batch_size=2)
    assert await stored(db, order_type) == incremental
    assert await verify_type(db, order_type, batch_size=2) == []


async def test_the_reindex_rebuilds_the_reduce_rows_too(db, order_type, settings):
    """``reindex_type`` is the repair for *every* derived row, not only the map
    ones — which is what makes `cli reindex` the fix a drift report names."""
    register_reduce_provider(state_spec())
    await make(db, order_type, settings, "CA", 10)
    await db.execute(delete(IndexReduce))
    assert await stored(db, order_type) == {}

    await reindex_type(db, order_type, resolve_type_id=lambda _k: None, batch_size=10)
    assert await stored(db, order_type) == {"CA": (1, Decimal("10.00000"))}


async def test_a_rebuild_with_no_spec_registered_writes_nothing(db_state, db, order_type):
    """Inert when unused, in the rebuild as well as on the write path: no spec
    means not even a ``DELETE`` per type on every reindex."""
    from tests.perf._bench import capture

    with capture(db_state.engine) as box:
        assert await rebuild_type(db, order_type, batch_size=10) == 0
    assert box.matching("records_index_reduce") == []


async def test_verify_reports_an_injected_drift_and_names_the_group(db, order_type, settings):
    """Drift cannot be produced through the API — that is the point — so it is
    injected directly, which is exactly what a lost increment would leave."""
    register_reduce_provider(state_spec())
    await make(db, order_type, settings, "CA", 10)
    await db.execute(update(IndexReduce).where(IndexReduce.key == STATE).values(count=99))

    drifts = await verify_type(db, order_type, batch_size=10)
    assert len(drifts) == 1
    assert drifts[0].group == "CA"
    assert drifts[0].stored[0] == 99 and drifts[0].actual[0] == 1
    assert "CA" in drifts[0].describe()


async def test_a_group_the_records_no_longer_produce_is_drift(db, order_type, settings):
    register_reduce_provider(state_spec())
    await make(db, order_type, settings, "CA", 10)
    db.add(
        IndexReduce(
            type_id=order_type.id,
            key=STATE,
            group_value="ZZ",
            count=3,
            sum=Decimal("1"),
            updated_at=utcnow(),
        )
    )
    await db.flush()
    drifts = await verify_type(db, order_type, batch_size=10)
    assert [(d.group, d.actual) for d in drifts] == [("ZZ", None)]


async def test_the_health_check_shows_drift_then_clears_it(db, order_type, settings):
    """The design says drift must be *detectable*; a verifier whose output
    scrolls past in a terminal is not detection. The last verify's result is
    what ``/health/ready`` reports, and a rebuild answers it."""
    from simple_module_core.health import HealthStatus

    register_reduce_provider(state_spec())
    await make(db, order_type, settings, "CA", 10)
    await db.execute(update(IndexReduce).where(IndexReduce.key == STATE).values(count=99))
    await verify_type(db, order_type, batch_size=10)
    assert current_drift() == {order_type.id: {STATE: 1}}

    module = _module_with(db)
    result = await stale_reindex_check(module).check()
    assert result.status is HealthStatus.DEGRADED
    assert STATE in (result.detail or "")

    await rebuild_type(db, order_type, batch_size=10)
    assert current_drift() == {}
    assert (await stale_reindex_check(module).check()).status is HealthStatus.HEALTHY


def _module_with(db):
    """A stand-in for the module instance the real check closes over — it only
    ever reads ``db`` and ``settings`` off it (``health``'s docstring)."""
    from types import SimpleNamespace

    class _State:
        session_factory = staticmethod(lambda: _Ctx(db))

    return SimpleNamespace(db=_State(), settings=None)


class _Ctx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *_exc):
        return False


@pytest_asyncio.fixture
async def file_db(tmp_path):
    """A real SQLite *file* on the default pool — one connection per session,
    exactly as a server has. See ``test_unique_concurrency``'s docstring."""
    state = init_db(f"sqlite+aiosqlite:///{tmp_path / 'reduce.db'}")
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def file_client(tmp_path, file_db):
    app, _ = await build_app(tmp_path, file_db)
    for dependency in (require_view, require_edit, require_manage_types):
        app.dependency_overrides[dependency.dependency] = lambda: None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_concurrent_writers_into_one_group_lose_no_increment(file_client, file_db):
    """Eight concurrent creates, one group, count **8**.

    This is why the increment is ``count = count + :d`` and never a Python
    read-modify-write: eight writers that each read ``n`` and stored ``n + 1``
    would leave a count somewhere between 1 and 8, and the failure would be a
    number that is merely wrong rather than an error anybody sees.
    """
    register_reduce_provider(state_spec(with_value=False))
    await seed_type(
        file_db,
        "order",
        [
            {"key": "state", "type": "text", "label": "State", "indexed": True},
            {"key": "name", "type": "text", "label": "Name", "indexed": True},
        ],
        display_field="name",
    )

    responses = await asyncio.gather(
        *(
            file_client.post(
                f"{API}/order/records", json={"data": {"state": "CA", "name": f"n{i}"}}
            )
            for i in range(WRITERS)
        )
    )
    assert [r.status_code for r in responses] == [201] * WRITERS

    async with file_db.session_factory() as session:
        rows = (
            (await session.execute(select(IndexReduce).where(IndexReduce.key == STATE)))
            .scalars()
            .all()
        )
    assert [(row.group_value, int(row.count)) for row in rows] == [("CA", WRITERS)]


async def test_the_cli_verify_reports_drift_and_exits_non_zero(tmp_path, capsys):
    """``python -m sm_records.cli reindex --verify``: the operator-facing half.

    Exit code 1 on drift and 0 clean, so it is usable as a deploy gate or a
    cron check without parsing the output — which in a repo with no queue is
    the only form a scheduled integrity check can take.
    """
    from sm_records.cli import run_verify
    from sm_records.settings import RecordsSettings

    url = f"sqlite+aiosqlite:///{tmp_path / 'verify.db'}"
    state = init_db(url)
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = RecordsSettings()
    register_reduce_provider(state_spec())
    async with state.session_factory() as session:
        from sm_records.services import types as type_service

        rtype = await type_service.create_type(
            session,
            key="order",
            label="Order",
            fields_raw=[
                {"key": "state", "type": "text", "label": "State", "indexed": True},
                {"key": "total", "type": "number", "label": "Total", "indexed": True},
                {"key": "name", "type": "text", "label": "Name", "indexed": True},
            ],
            settings=settings,
        )
        await make(session, rtype, settings, "CA", 10)
        await session.commit()
    await state.engine.dispose()

    assert await run_verify(url, None) == 0
    assert "clean across" in capsys.readouterr().out

    scratch = init_db(url)
    async with scratch.session_factory() as session:
        await session.execute(update(IndexReduce).values(count=42))
        await session.commit()
    await scratch.engine.dispose()

    assert await run_verify(url, None) == 1
    assert "DRIFT" in capsys.readouterr().out
