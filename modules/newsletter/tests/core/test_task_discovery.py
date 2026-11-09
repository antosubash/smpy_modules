"""Celery finds newsletter's tasks and their routing only at fixed module paths.

``background_tasks`` imports ``<package>.tasks`` (``autodiscover_tasks``) and
``<package>.task_config`` (routes, queues and beat) and looks nowhere else. A
worker started for a queue subset (``SM_BG_TASKS_WORKER_QUEUES``) imports a
package's tasks only when its ``QUEUES`` overlap - without them it would be
judged by the install's default queue and a ``newsletter`` worker would never
load the reconcile.
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
from sm_newsletter import task_config
from sm_newsletter.task_config import (
    BEAT_SCHEDULE,
    DISPATCH,
    IMPORT_JANITOR,
    RECONCILE_SUPPRESSIONS,
    RUN_IMPORT,
    TASK_ROUTES,
)


def test_the_task_module_sits_where_autodiscovery_imports_it():
    mod = importlib.import_module("sm_newsletter.tasks")
    names = {getattr(obj, "name", None) for obj in vars(mod).values()}
    assert {RECONCILE_SUPPRESSIONS, DISPATCH, RUN_IMPORT, IMPORT_JANITOR} <= names


def test_the_framework_loads_routes_and_beat_from_the_package():
    config = load_task_config("sm_newsletter")
    assert config is not None, "background_tasks found no sm_newsletter.task_config"
    assert config.routes == TASK_ROUTES
    assert config.beat_schedule == BEAT_SCHEDULE
    assert config.queues == frozenset({"newsletter"})


def test_the_reconcile_runs_hourly_on_the_newsletter_queue():
    assert task_config.RECONCILE_INTERVAL_SECONDS == 3600.0
    assert BEAT_SCHEDULE["newsletter-reconcile-suppressions"] == {
        "task": RECONCILE_SUPPRESSIONS,
        "schedule": 3600.0,
        "options": {"queue": "newsletter"},
    }
    assert TASK_ROUTES[RECONCILE_SUPPRESSIONS] == {"queue": "newsletter"}


def test_the_dispatcher_runs_every_minute_on_the_newsletter_queue():
    """``expires`` below the interval: a tick a stopped beat queued up is
    dropped rather than run late on top of the next one."""
    assert DISPATCH == "newsletter.dispatch"
    assert task_config.DISPATCH_INTERVAL_SECONDS == 60.0
    assert set(BEAT_SCHEDULE) == {
        "newsletter-reconcile-suppressions",
        "newsletter-dispatch",
        "newsletter-import-janitor",
    }
    assert BEAT_SCHEDULE["newsletter-dispatch"] == {
        "task": DISPATCH,
        "schedule": 60.0,
        "options": {"queue": "newsletter", "expires": 55},
    }
    assert TASK_ROUTES == {
        RECONCILE_SUPPRESSIONS: {"queue": "newsletter"},
        DISPATCH: {"queue": "newsletter"},
        RUN_IMPORT: {"queue": "newsletter"},
        IMPORT_JANITOR: {"queue": "newsletter"},
    }


def test_the_import_janitor_runs_hourly_on_the_newsletter_queue():
    assert (RUN_IMPORT, IMPORT_JANITOR) == ("newsletter.run_import", "newsletter.import_janitor")
    assert task_config.JANITOR_INTERVAL_SECONDS == 3600.0
    assert BEAT_SCHEDULE["newsletter-import-janitor"] == {
        "task": IMPORT_JANITOR,
        "schedule": 3600.0,
        "options": {"queue": "newsletter"},
    }


def test_a_worker_scoped_to_the_newsletter_queue_imports_the_newsletter_tasks():
    # A package with no task_config is judged by the install's default queue.
    packages = ["sm_newsletter", "sm_newsletter_test_absent"]
    configs = load_task_configs(packages)
    settings = BackgroundTasksSettings()

    def chosen(*queues: str) -> list[str]:
        scope = WorkerScope(queues=frozenset(queues))
        return select_packages(packages, configs, settings, scope=scope)

    default = settings.task_default_queue
    assert chosen("newsletter") == ["sm_newsletter"]
    assert chosen("images", "newsletter", default) == packages  # `make worker`'s -Q
    assert chosen("images") == []
    # Its queue is not the default one, so a default-queue worker skips it.
    assert chosen(default) == ["sm_newsletter_test_absent"]
