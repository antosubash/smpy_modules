"""The Celery side: the task runs through the worker runtime, with no app.

Synchronous tests on purpose - a prefork child has no running event loop, and
the task body starts its own (``asyncio.run``).
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from background_tasks.core import sync_db
from sm_events import tasks
from sm_events.core import worker
from sm_events.core.tenancy import tenant_scope
from sm_events.core.tenancy._guard import is_guarded
from sm_events.models import Calendar, Event

from tests.pg_support import USING_POSTGRES, make_db_state
from tests.support.calendars import seed_event

pytestmark = pytest.mark.skipif(
    USING_POSTGRES, reason="the worker test points sync_db at its own SQLite file"
)

PAST = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture
def worker_db(tmp_path):
    """A file database the worker reaches only through ``sync_db``'s URL, with one
    due event in tenant ``default``."""
    db_file = tmp_path / "worker.db"

    async def seed():
        state = await make_db_state(file=db_file)
        with tenant_scope("default"):
            async with state.session_factory() as s:
                cal = Calendar(slug="c", name="c", owner_id="o")
                s.add(cal)
                await s.flush()
                await seed_event(s, cal, title="due", status="draft", publish_at=PAST)
                await s.commit()
        await state.engine.dispose()

    asyncio.run(seed())
    sync_db.set_database_url(f"sqlite:///{db_file}")
    worker.reset_worker_runtime()
    yield db_file
    worker.reset_worker_runtime()
    sync_db.set_database_url(None)
    sync_db.dispose_sync_engine()


async def _statuses(db_file) -> list[str]:
    state = await make_db_state(file=db_file)
    with tenant_scope("default"):
        async with state.session_factory() as s:
            from sqlalchemy import select

            rows = list((await s.execute(select(Event.status))).scalars())
    await state.engine.dispose()
    return rows


def test_the_task_unbinds_the_callers_tenant(worker_db):
    """Run under the suite's bound ``default``: the platform pass unbinds it, or
    the tenant enumeration would refuse."""
    assert tasks.publish_due() == {"tenants": 1, "published": 1, "failed": 0}
    assert asyncio.run(_statuses(worker_db)) == ["published"]
    assert tasks.publish_due() == {"tenants": 0, "published": 0, "failed": 0}  # redelivery


async def test_a_task_body_refuses_a_running_loop():
    with pytest.raises(RuntimeError, match="event loop"):
        tasks.publish_due()


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
    from sm_events.task_config import PUBLISH_DUE

    assert PUBLISH_DUE in current_app.tasks
    assert not hasattr(tasks, "BEAT_SCHEDULE")  # one place, or the entry doubles
