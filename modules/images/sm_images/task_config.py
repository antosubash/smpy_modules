"""Light Celery configuration, read by ``background_tasks`` without importing tasks.

* ``images`` - light steps (``exif``, ``renditions``), ``images.reconcile``
  (routed here rather than behind a long import) and the daily
  ``images.janitor``;
* ``images_imports`` - the orchestrators (``images.restart_collection``,
  ``images.import_geojson``, ``images.reset_import``); run its worker with concurrency 1. Downloads
  (``images.download_items``) go to ``images``, so a long import stream never
  blocks its own downloads;
* ``images_heavy`` / ``images_gpu`` - plugin steps that declare them.

``images.run_step``'s route is only a default: each message carries the queue
of the step it runs (``step.queue``), which wins over a route. Beat lives here
and only here, so the entry is never merged twice.
"""

from __future__ import annotations

RUN_STEP = "images.run_step"
RESTART_COLLECTION = "images.restart_collection"
RECONCILE = "images.reconcile"
JANITOR = "images.janitor"
IMPORT_GEOJSON = "images.import_geojson"
DOWNLOAD_ITEMS = "images.download_items"
RESET_IMPORT = "images.reset_import"

QUEUE_DEFAULT = "images"
QUEUE_IMPORTS = "images_imports"
QUEUES = {QUEUE_DEFAULT, QUEUE_IMPORTS, "images_heavy", "images_gpu"}

TASK_ROUTES = {
    RUN_STEP: {"queue": QUEUE_DEFAULT},
    RESTART_COLLECTION: {"queue": QUEUE_IMPORTS},
    RECONCILE: {"queue": QUEUE_DEFAULT},
    JANITOR: {"queue": QUEUE_DEFAULT},
    IMPORT_GEOJSON: {"queue": QUEUE_IMPORTS},
    DOWNLOAD_ITEMS: {"queue": QUEUE_DEFAULT},
    RESET_IMPORT: {"queue": QUEUE_IMPORTS},
}

RECONCILE_INTERVAL_SECONDS = 300.0
JANITOR_INTERVAL_SECONDS = 24 * 3600.0

BEAT_SCHEDULE = {
    "images-reconcile": {
        "task": RECONCILE,
        "schedule": RECONCILE_INTERVAL_SECONDS,
        "options": {"queue": QUEUE_DEFAULT},
    },
    "images-janitor": {
        "task": JANITOR,
        "schedule": JANITOR_INTERVAL_SECONDS,
        "options": {"queue": QUEUE_DEFAULT},
    },
}
