"""Celery finds images' tasks only at ``sm_images.tasks``.

``background_tasks`` calls ``autodiscover_tasks(packages, related_name="tasks")``,
which imports ``<package>.tasks`` and nothing else. Moving the module into a
subpackage would leave every worker without images' tasks while the tests,
which import it by whatever path it has, kept passing.
"""

from __future__ import annotations

import importlib

from sm_images.jobs.task_config import JANITOR, RUN_STEP


def test_the_task_module_sits_where_autodiscovery_imports_it():
    mod = importlib.import_module("sm_images.tasks")
    names = {getattr(obj, "name", None) for obj in vars(mod).values()}
    assert {RUN_STEP, JANITOR} <= names
