"""``launch`` and the ``run_import`` task (R13, D2, D6): eager slices inline, a message otherwise,
a chain of messages to ``done``, and a task result that never carries an exception."""

from __future__ import annotations

import asyncio
import logging

import pytest
import pytest_asyncio
from sm_newsletter import tasks
from sm_newsletter.core import worker
from sm_newsletter.imports import launch as launch_mod
from sm_newsletter.imports import runner
from sm_newsletter.task_config import QUEUE_DEFAULT

from tests.imports.world import FIELDS
from tests.support.app import build_app
from tests.support.import_world import NOW, SETTINGS, counts, export, job_row, staged_count
from tests.support.records_seed import seed_list

pytestmark = pytest.mark.unbound_tenant

SENTINEL = "sentinel-7f3a"


@pytest_asyncio.fixture
async def world(tmp_path, monkeypatch):
    app, st = await build_app(file=tmp_path / "launch.db")
    await seed_list(st, "default", fields=FIELDS)
    monkeypatch.setattr(runner, "BATCH_SIZE", 2)
    monkeypatch.setattr(runner, "SLICE_SECONDS", 0)
    monkeypatch.setattr(runner, "utcnow", lambda: NOW)
    yield app, st
    await st.engine.dispose()


def bridge(monkeypatch, st) -> asyncio.AbstractEventLoop:
    """Let the task body (which starts its own loop) run against the test's engine: its
    coroutine is handed to the test loop from the worker thread."""
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        worker,
        "run_platform",
        lambda body: asyncio.run_coroutine_threadsafe(body(st.session_factory), loop).result(),
    )
    monkeypatch.setattr(launch_mod, "records_worker_settings", lambda: SETTINGS)
    return loop


async def test_eager_launch_runs_inline_to_done(world, monkeypatch):
    app, st = world
    monkeypatch.setattr(launch_mod, "celery_eager", lambda: True)
    jid = await export(st)
    await launch_mod.launch(app, tenant_id="default", import_id=jid)
    job = await job_row(st, jid)
    assert job.status == "done"
    assert counts(job) == (3, 0, 0, 3, 0)
    assert await staged_count(st, jid) == 0


async def test_eager_launch_swallows_a_failure(world, monkeypatch):
    app, st = world
    monkeypatch.setattr(launch_mod, "celery_eager", lambda: True)

    async def boom(*a, **kw):
        raise LookupError(SENTINEL)

    monkeypatch.setattr("sm_newsletter.imports.apply.import_subscribers", boom)
    jid = await export(st)
    await launch_mod.launch(app, tenant_id="default", import_id=jid)
    assert (await job_row(st, jid)).status == "failed"


async def test_broker_launch_sends_message(world, monkeypatch):
    app, st = world
    monkeypatch.setattr(launch_mod, "celery_eager", lambda: False)
    sent = []
    from celery.canvas import Signature

    def record(self, args=None, kwargs=None, **options):
        sent.append((self.task, self.args, options))

    monkeypatch.setattr(Signature, "apply_async", record)
    jid = await export(st)
    await launch_mod.launch(app, tenant_id="default", import_id=jid)
    assert sent == [("newsletter.run_import", ("default", jid), {"queue": QUEUE_DEFAULT})]
    assert (await job_row(st, jid)).status == "queued"


async def test_task_chains_slices_to_done(world, monkeypatch):
    _app, st = world
    bridge(monkeypatch, st)
    jid = await export(st)
    results: list[str] = []

    def again(self, args=None, kwargs=None, **options):
        assert options == {"queue": QUEUE_DEFAULT}
        results.append(tasks.run_import(*self.args))

    from celery.canvas import Signature

    monkeypatch.setattr(Signature, "apply_async", again)
    first = await asyncio.to_thread(tasks.run_import, "default", jid)
    assert first == "more"
    assert sorted(results) == ["done", "more", "more"]  # appended innermost first
    assert "busy" not in results
    assert (await job_row(st, jid)).status == "done"


async def test_task_result_is_sanitised(world, monkeypatch, caplog):
    _app, st = world
    bridge(monkeypatch, st)

    async def boom(*a, **kw):
        raise LookupError(SENTINEL)

    monkeypatch.setattr("sm_newsletter.imports.apply.import_subscribers", boom)
    jid = await export(st)
    caplog.set_level(logging.DEBUG)
    result = await asyncio.to_thread(lambda: tasks.run_import.apply(args=("default", jid)))
    assert result.result == "failed"
    assert SENTINEL not in str(result.traceback or "")
    assert SENTINEL not in caplog.text
    job = await job_row(st, jid)
    assert (job.status, job.error_code) == ("failed", "import_failed")
    assert SENTINEL not in repr(job.errors)


def test_records_worker_settings_reads_settings_for(monkeypatch):
    import background_tasks
    from sm_records.contracts.newsletter_import import RECORDS_PACKAGE, RecordsSettings

    seen = []
    sentinel = object()
    monkeypatch.setattr(
        background_tasks, "settings_for", lambda cls, pkg: seen.append((cls, pkg)) or sentinel
    )
    assert launch_mod.records_worker_settings() is sentinel
    assert seen == [(RecordsSettings, RECORDS_PACKAGE)]


def test_celery_eager_reads_the_app_conf(monkeypatch):
    from celery import current_app

    monkeypatch.setitem(current_app.conf, "task_always_eager", True)
    assert launch_mod.celery_eager() is True
    monkeypatch.setitem(current_app.conf, "task_always_eager", False)
    assert launch_mod.celery_eager() is False
