"""Celery finds images' tasks and their routing only at fixed module paths.

``background_tasks`` imports ``<package>.tasks`` (``autodiscover_tasks``) and
``<package>.task_config`` (routes and beat) and looks nowhere else. Moving
either into a subpackage leaves every worker without images' tasks, or without
their queues and schedules, while the tests, which import the module by
whatever path it has, keep passing.
"""

from __future__ import annotations

import importlib

from background_tasks.task_routing import load_task_config
from sm_images.task_config import BEAT_SCHEDULE, JANITOR, RUN_STEP, TASK_ROUTES


def test_the_task_module_sits_where_autodiscovery_imports_it():
    mod = importlib.import_module("sm_images.tasks")
    names = {getattr(obj, "name", None) for obj in vars(mod).values()}
    assert {RUN_STEP, JANITOR} <= names


def test_the_framework_loads_routes_and_beat_from_the_package():
    config = load_task_config("sm_images")
    assert config is not None, "background_tasks found no sm_images.task_config"
    assert config.routes == TASK_ROUTES
    assert config.beat_schedule == BEAT_SCHEDULE
