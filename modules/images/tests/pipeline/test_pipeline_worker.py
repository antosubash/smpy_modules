"""The Celery side: task bodies run through the worker runtime, with no app.

These are synchronous tests on purpose - a prefork child has no running event
loop, and the task body starts its own (``asyncio.run``).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from background_tasks import sync_db
from background_tasks.worker_settings import clear_settings_cache
from simple_module_db import tenant_context
from simple_module_db.stored_settings import Base as SettingsBase
from simple_module_db.stored_settings import Setting
from sm_images import task_config, tasks
from sm_images.core.storage import intents, reset_worker_store
from sm_images.core.tenancy import DEFAULT_TENANT, TenantUnbound
from sm_images.models import Rendition, StepRun
from sm_images.pipeline import registry
from sm_images.pipeline import worker_runtime as wr
from sm_images.pipeline.advance import plan_and_claim
from sqlalchemy import select

from tests.pg_support import USING_POSTGRES, make_db_state
from tests.support.pipeline import make_pipe, use_steps

pytestmark = pytest.mark.skipif(
    USING_POSTGRES, reason="the worker test points sync_db at its own SQLite file"
)


@pytest.fixture
def worker_db(tmp_path):
    """A file database the worker runtime reaches only through ``sync_db``'s URL,
    with ``file_storage``'s root stored as a DB-backed setting."""
    db_file = tmp_path / "worker.db"
    root = tmp_path / "objects"
    use_steps()

    async def seed():
        state = await make_db_state(file=db_file)
        async with state.engine.begin() as conn:
            await conn.run_sync(SettingsBase.metadata.create_all)
        async with state.session_factory() as s:
            s.add(Setting(key="file_storage.fs_root_path", value=str(root)))
            sizes = json.dumps({"tiny": 8})
            s.add(Setting(key="sm_images.thumbnail_sizes", value=sizes, value_type="json"))
            await s.commit()
        pipe = await make_pipe(tmp_path, state)
        pipe.backend.root = root
        with tenant_context(DEFAULT_TENANT):
            coll = await pipe.collection({"renditions": {}})
            img = await pipe.image(coll)
            async with state.session_factory() as s:
                found = await plan_and_claim(s, DEFAULT_TENANT, img, datetime.now(UTC), 1800)
                await s.commit()
        await state.engine.dispose()
        return img, found.claims[0].token

    image_id, token = asyncio.run(seed())
    sync_db.set_database_url(f"sqlite:///{db_file}")
    clear_settings_cache()
    reset_worker_store()
    wr.reset_worker_runtime()
    yield SimpleNamespace(file=db_file, root=root, image_id=image_id, token=token)
    wr.reset_worker_runtime()
    reset_worker_store()
    clear_settings_cache()
    sync_db.dispose_sync_engine()
    registry.reset_registry()


async def _rows(db_file, model):
    state = await make_db_state(file=db_file)
    with tenant_context(DEFAULT_TENANT):
        async with state.session_factory() as s:
            rows = list((await s.execute(select(model))).scalars())
    await state.engine.dispose()
    return rows


@pytest.mark.unbound_tenant
def test_task_body_runs_through_the_worker_runtime(worker_db):
    """``images.run_step`` called as a worker calls it: no app, no loop, the
    tenant the message header restored, the DB from ``sync_db``, the store from
    the DB-backed ``file_storage`` settings, the intent factory the worker's."""
    with tenant_context(DEFAULT_TENANT):  # what task_prerun restores from the header
        tasks.run_step(str(worker_db.image_id), "renditions", str(worker_db.token))
    runs = asyncio.run(_rows(worker_db.file, StepRun))
    assert [(r.step, r.status.value) for r in runs] == [("renditions", "completed")]
    made = asyncio.run(_rows(worker_db.file, Rendition))
    assert [(r.size, max(r.width, r.height)) for r in made] == [("tiny", 8)]  # stored setting
    on_disk = {p.name for p in worker_db.root.rglob("*.jpg")}
    assert len(on_disk) == 2  # the original and the rendition, under the stored root
    assert intents.current_factory() is wr.worker_session_factory()


@pytest.mark.unbound_tenant
def test_task_without_a_tenant_fails_closed_on_a_multi_tenant_host(worker_db):
    sync_db.set_database_url(f"sqlite:///{worker_db.file}", tenant_strict=True)
    with pytest.raises(TenantUnbound):
        tasks.run_step(str(worker_db.image_id), "renditions", str(worker_db.token))


@pytest.mark.unbound_tenant
def test_single_tenant_host_falls_back_to_its_default_tenant(worker_db):
    tasks.run_step(str(worker_db.image_id), "renditions", str(worker_db.token))
    runs = asyncio.run(_rows(worker_db.file, StepRun))
    assert runs[0].status.value == "completed"


async def test_a_task_body_refuses_a_running_loop():
    with pytest.raises(RuntimeError, match="event loop"):
        tasks.run_step(str(uuid.uuid4()), "exif", str(uuid.uuid4()))


def test_engine_is_rebuilt_in_a_forked_child(worker_db, monkeypatch):
    import os

    first = wr.worker_session_factory()
    assert wr.worker_session_factory() is first
    pid = os.getpid()
    monkeypatch.setattr(os, "getpid", lambda: pid + 1)
    assert wr.worker_session_factory() is not first


def test_worker_ready_sends_one_reconcile():
    sent: list = []
    sender = SimpleNamespace(
        app=SimpleNamespace(send_task=lambda name, **kw: sent.append((name, kw)))
    )
    tasks.reconcile_on_ready(sender=sender)
    assert sent == [(task_config.RECONCILE, {"queue": "images"})]


def test_worker_ready_survives_a_broker_failure():
    def down(name, **kw):
        raise ConnectionError("broker down")

    tasks.reconcile_on_ready(sender=SimpleNamespace(app=SimpleNamespace(send_task=down)))


def test_task_config_routes_and_beat():
    assert {"images", "images_imports", "images_heavy", "images_gpu"} == task_config.QUEUES
    assert task_config.TASK_ROUTES[task_config.RESTART_COLLECTION] == {"queue": "images_imports"}
    assert task_config.TASK_ROUTES[task_config.RECONCILE] == {"queue": "images"}
    entries = {e["task"]: e["schedule"] for e in task_config.BEAT_SCHEDULE.values()}
    assert entries == {task_config.RECONCILE: 300.0, task_config.JANITOR: 86400.0}
    assert not hasattr(tasks, "BEAT_SCHEDULE")  # one place, or the entry doubles


def test_tasks_are_registered_under_their_names():
    from celery import current_app

    names = (
        task_config.RUN_STEP,
        task_config.RESTART_COLLECTION,
        task_config.RECONCILE,
        task_config.JANITOR,
    )
    for name in names:
        assert name in current_app.tasks
