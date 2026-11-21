"""Celery finds events' tasks and their routing only at fixed module paths.

``background_tasks`` imports ``<package>.tasks`` (``autodiscover_tasks``) and
``<package>.task_config`` (routes, queues and beat) and looks nowhere else. A
worker started for a queue subset (``SM_BG_TASKS_WORKER_QUEUES``) imports a
package's tasks only when its ``QUEUES`` overlap.
"""

from __future__ import annotations

import importlib

from background_tasks.core.config_guards import WorkerScope
from background_tasks.core.settings import BackgroundTasksSettings
from background_tasks.worker.task_routing import (
    load_task_config,
    load_task_configs,
    select_packages,
)
from sm_events.task_config import BEAT_SCHEDULE, PUBLISH_DUE, TASK_ROUTES


def test_the_task_module_sits_where_autodiscovery_imports_it():
    mod = importlib.import_module("sm_events.tasks")
    names = {getattr(obj, "name", None) for obj in vars(mod).values()}
    assert PUBLISH_DUE in names


def test_the_framework_loads_routes_and_beat_from_the_package():
    config = load_task_config("sm_events")
    assert config is not None, "background_tasks found no sm_events.task_config"
    assert config.routes == TASK_ROUTES
    assert config.beat_schedule == BEAT_SCHEDULE
    assert config.queues == frozenset({"events"})


def test_publish_due_runs_every_minute_on_the_events_queue():
    """``expires`` below the interval: a tick a stopped beat queued up is dropped
    rather than run late on top of the next one."""
    assert PUBLISH_DUE == "events.publish_due"
    assert BEAT_SCHEDULE == {
        "events-publish-due": {
            "task": PUBLISH_DUE,
            "schedule": 60.0,
            "options": {"queue": "events", "expires": 55},
        }
    }
    assert TASK_ROUTES == {PUBLISH_DUE: {"queue": "events"}}


def test_a_worker_scoped_to_the_events_queue_imports_the_events_tasks():
    # A package with no task_config is judged by the install's default queue.
    packages = ["sm_events", "sm_events_test_absent"]
    configs = load_task_configs(packages)
    settings = BackgroundTasksSettings()

    def chosen(*queues: str) -> list[str]:
        scope = WorkerScope(queues=frozenset(queues))
        return select_packages(packages, configs, settings, scope=scope)

    default = settings.task_default_queue
    assert chosen("events") == ["sm_events"]
    assert chosen("images", "newsletter", "events", default) == packages  # `make worker`'s -Q
    assert chosen("images") == []
    assert chosen(default) == ["sm_events_test_absent"]
