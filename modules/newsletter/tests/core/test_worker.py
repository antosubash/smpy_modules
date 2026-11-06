"""The Celery side: the reconcile task runs through the worker runtime, with no app.

Synchronous tests on purpose - a prefork child has no running event loop, and
the task body starts its own (``asyncio.run``).
"""

from __future__ import annotations

import asyncio
import logging
import os

import pytest
from background_tasks import sync_db
from sm_newsletter import tasks
from sm_newsletter.core import worker
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.core.tenancy._guard import is_guarded
from sm_newsletter.models import Suppression
from sqlalchemy import select

from tests.pg_support import USING_POSTGRES, make_db_state
from tests.support.records_seed import seed_list, seed_subscriber

pytestmark = pytest.mark.skipif(
    USING_POSTGRES, reason="the worker test points sync_db at its own SQLite file"
)


@pytest.fixture
def worker_db(tmp_path):
    """A file database the worker reaches only through ``sync_db``'s URL, with
    one unsubscribed subscriber on a list in tenant ``default``."""
    db_file = tmp_path / "worker.db"

    async def seed():
        state = await make_db_state(file=db_file)
        await seed_list(state, "default")
        await seed_subscriber(state, "default", "ada@example.org", "unsubscribed")
        await state.engine.dispose()

    asyncio.run(seed())
    sync_db.set_database_url(f"sqlite:///{db_file}")
    worker.reset_worker_runtime()
    yield db_file
    worker.reset_worker_runtime()
    sync_db.set_database_url(None)
    sync_db.dispose_sync_engine()


async def _sources(db_file) -> list[str]:
    state = await make_db_state(file=db_file)
    with tenant_scope("default"):
        async with state.session_factory() as s:
            rows = list((await s.execute(select(Suppression.source))).scalars())
    await state.engine.dispose()
    return rows


@pytest.mark.unbound_tenant
def test_reconcile_task_runs_through_the_worker_runtime(worker_db, caplog):
    with caplog.at_level(logging.INFO, logger=tasks.__name__):
        summary = tasks.reconcile_suppressions()
    assert summary == {"lists": 1, "suppressed": 1, "failed": 0}
    assert asyncio.run(_sources(worker_db)) == ["reconcile"]
    assert "1 list(s), 1 new suppression(s), 0 failed" in caplog.text
    assert tasks.reconcile_suppressions()["suppressed"] == 0  # idempotent


def test_the_task_unbinds_the_callers_tenant(worker_db):
    """Run under the suite's bound ``default``: the platform pass unbinds it,
    or the contract's tenant enumeration would refuse."""
    assert tasks.reconcile_suppressions()["lists"] == 1


async def test_a_task_body_refuses_a_running_loop():
    with pytest.raises(RuntimeError, match="event loop"):
        tasks.reconcile_suppressions()


def test_worker_engine_is_guarded_and_rebuilt_in_a_forked_child(worker_db, monkeypatch):
    first = worker.worker_session_factory()
    assert worker.worker_session_factory() is first
    assert is_guarded(worker._engine[2].sync_session_class)
    pid = os.getpid()
    monkeypatch.setattr(os, "getpid", lambda: pid + 1)
    assert worker.worker_session_factory() is not first


def test_worker_process_init_forgets_the_runtime(worker_db):
    worker.worker_session_factory()
    tasks.forget_parent_runtime()
    assert worker._engine is None


def test_the_task_is_registered_under_its_name():
    from celery import current_app
    from sm_newsletter.task_config import RECONCILE_SUPPRESSIONS

    assert RECONCILE_SUPPRESSIONS in current_app.tasks
    assert not hasattr(tasks, "BEAT_SCHEDULE")  # one place, or the entry doubles
