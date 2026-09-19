"""When the rebuild never runs: the alarm, and the command that finishes it.

Design doc §8.9. A background task that died with its worker leaves
``reindex_pending`` set, which is recoverable — but "recoverable" is not
"visible", and a field that refuses filters forever is otherwise only noticed
by whoever next tries that filter. So the module contributes a health check
that degrades on a stale marker and names the type and fields, and a CLI
command that clears them.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from simple_module_core.health import HealthStatus
from sm_records.constants import REINDEX_ALL
from sm_records.health import stale_reindex_check
from sm_records.models import IndexNumber, RecordType
from sm_records.services import records as record_service
from sm_records.services import schema_change
from sm_records.services import types as type_service
from sm_records.settings import RecordsSettings
from sqlalchemy import select


@pytest.fixture
def settings() -> RecordsSettings:
    return RecordsSettings()


# --- the alarm (§8.9) -------------------------------------------------------


def module_for(db_state, **overrides):
    """What ``on_startup`` parks on the module instance, and nothing else —
    the check is written to need exactly this much."""
    return SimpleNamespace(db=db_state, settings=RecordsSettings(**overrides))


async def test_the_health_check_is_healthy_before_the_database_is_open():
    check = stale_reindex_check(SimpleNamespace(db=None, settings=None))
    assert (await check.check()).status is HealthStatus.HEALTHY


async def test_the_health_check_degrades_on_a_pending_entry_that_is_too_old(
    db, db_state, settings, field_def
):
    rtype = await type_service.create_type(
        db,
        key="product",
        label="Product",
        fields_raw=[field_def("price", "number")],
        settings=settings,
    )
    rtype.reindex_pending = {
        "price": "2020-01-01T00:00:00+00:00",
        REINDEX_ALL: "2020-01-01T00:00:00+00:00",
    }
    db.add(rtype)
    await db.commit()

    result = await stale_reindex_check(module_for(db_state)).check()
    assert result.status is HealthStatus.DEGRADED
    assert "product" in result.detail
    assert "price" in result.detail and "whole type" in result.detail


async def test_a_fresh_pending_entry_is_not_an_alarm(db, db_state, settings, field_def):
    from sm_records.services._common import utcnow

    rtype = await type_service.create_type(
        db,
        key="product",
        label="Product",
        fields_raw=[field_def("price", "number")],
        settings=settings,
    )
    rtype.reindex_pending = {"price": utcnow().isoformat()}
    db.add(rtype)
    await db.commit()

    result = await stale_reindex_check(module_for(db_state)).check()
    assert result.status is HealthStatus.HEALTHY


# --- the CLI (§7.7) ---------------------------------------------------------


async def test_the_cli_reindex_command_finishes_every_pending_rebuild(tmp_path, field_def, capsys):
    """Against a file database, because the command opens its own engine — the
    recovery path an operator runs after a worker restart ate the task."""
    from simple_module_db.listeners import register_listeners
    from simple_module_db.session import init_db
    from sm_records.cli import reindex
    from sm_records.models import Base

    url = f"sqlite+aiosqlite:///{tmp_path / 'records.db'}"
    state = init_db(url)
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = RecordsSettings()
    async with state.session_factory() as session:
        rtype = await type_service.create_type(
            session,
            key="product",
            label="Product",
            fields_raw=[field_def("price", "text")],
            settings=settings,
        )
        await record_service.create_record(session, rtype, data={"price": "12"}, settings=settings)
        await schema_change.apply(
            session,
            rtype,
            fields_raw=[field_def("price", "number")],
            expected_version=1,
            settings=settings,
        )
        await session.commit()
    await state.engine.dispose()

    assert await reindex(url, None) == 1
    assert "product — 1 record(s)" in capsys.readouterr().out

    check = init_db(url)
    async with check.session_factory() as session:
        fresh = (await session.execute(select(RecordType))).scalars().one()
        assert fresh.reindex_pending == {}
        rows = (await session.execute(select(IndexNumber))).scalars().all()
        assert len(rows) == 1
    await check.engine.dispose()
