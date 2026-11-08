"""Light Celery configuration, read by ``background_tasks`` without importing tasks.

* ``newsletter`` - ``newsletter.reconcile_suppressions``, the hourly re-read of
  records' opt-outs into the suppression store, and ``newsletter.dispatch``,
  the dispatcher tick every minute. A tick stops starting new work after 50 s
  (``sending.dispatch.TICK_SECONDS``), and a queued one expires after 55 s, so a
  backlog (a stopped worker, a slow broker) is dropped rather than run late on
  top of the next tick.
* ``newsletter.run_import`` (one slice of a Mailchimp import, re-enqueued until
  done) and ``newsletter.import_janitor``, the hourly expiry of unapplied
  imports and relaunch of lost ones.

``QUEUES`` is what a worker started for a queue subset
(``SM_BG_TASKS_WORKER_QUEUES``) checks before it imports ``sm_newsletter.tasks``;
without it the package would be judged by the install's default queue. Beat
lives here and only here, so the entry is never merged twice. Keep this file
free of heavy imports (and of celery).
"""

from __future__ import annotations

RECONCILE_SUPPRESSIONS = "newsletter.reconcile_suppressions"
DISPATCH = "newsletter.dispatch"
RUN_IMPORT = "newsletter.run_import"
IMPORT_JANITOR = "newsletter.import_janitor"

QUEUE_DEFAULT = "newsletter"
QUEUES = {QUEUE_DEFAULT}

TASK_ROUTES = {
    RECONCILE_SUPPRESSIONS: {"queue": QUEUE_DEFAULT},
    DISPATCH: {"queue": QUEUE_DEFAULT},
    RUN_IMPORT: {"queue": QUEUE_DEFAULT},
    IMPORT_JANITOR: {"queue": QUEUE_DEFAULT},
}

RECONCILE_INTERVAL_SECONDS = 3600.0
DISPATCH_INTERVAL_SECONDS = 60.0
JANITOR_INTERVAL_SECONDS = 3600.0

BEAT_SCHEDULE = {
    "newsletter-reconcile-suppressions": {
        "task": RECONCILE_SUPPRESSIONS,
        "schedule": RECONCILE_INTERVAL_SECONDS,
        "options": {"queue": QUEUE_DEFAULT},
    },
    "newsletter-dispatch": {
        "task": DISPATCH,
        "schedule": DISPATCH_INTERVAL_SECONDS,
        "options": {"queue": QUEUE_DEFAULT, "expires": 55},
    },
    "newsletter-import-janitor": {
        "task": IMPORT_JANITOR,
        "schedule": JANITOR_INTERVAL_SECONDS,
        "options": {"queue": QUEUE_DEFAULT},
    },
}
