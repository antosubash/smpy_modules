"""The celery task body: the platform runtime, then one pass."""

from __future__ import annotations

import pytest
from sm_events import tasks
from sm_events.core.settings import EventsSettings
from sm_events.reminders import tick, worker_app

from tests.core.test_worker import worker_db  # noqa: F401 - fixture


def test_the_task_runs_one_pass_through_the_worker_runtime(worker_db, monkeypatch):  # noqa: F811
    seen = []

    async def runtime(db):
        seen.append("asked")
        return  # this process cannot resolve accounts: unavailable, not a crash

    monkeypatch.setattr(worker_app, "worker_runtime", runtime)
    monkeypatch.setattr(tick, "_stored_settings", lambda: EventsSettings())
    got = tasks.reminders()  # under the suite's bound tenant: the platform runtime unbinds it
    assert seen == ["asked"]
    assert got["unavailable"] == 1 and got["sent"] == 0


async def test_the_task_refuses_a_running_loop():
    with pytest.raises(RuntimeError, match="event loop"):
        tasks.reminders()
