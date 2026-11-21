"""Light Celery configuration, read by ``background_tasks`` without importing tasks.

* ``events`` - ``events.publish_due``, the beat every minute that publishes the
  events whose ``publish_at`` has come. A queued tick expires after 55 s, so a
  backlog (a stopped worker, a slow broker) is dropped rather than run late on
  top of the next tick: the next one picks the same rows up.

``QUEUES`` is what a worker started for a queue subset
(``SM_BG_TASKS_WORKER_QUEUES``) checks before it imports ``sm_events.tasks``.
Beat lives here and only here, so the entry is never merged twice. A host
without beat never publishes on a schedule. Keep this file free of heavy
imports (and of celery).
"""

from __future__ import annotations

PUBLISH_DUE = "events.publish_due"

QUEUE_DEFAULT = "events"
QUEUES = {QUEUE_DEFAULT}

TASK_ROUTES = {PUBLISH_DUE: {"queue": QUEUE_DEFAULT}}

PUBLISH_DUE_INTERVAL_SECONDS = 60.0
PUBLISH_DUE_EXPIRES_SECONDS = 55

BEAT_SCHEDULE = {
    "events-publish-due": {
        "task": PUBLISH_DUE,
        "schedule": PUBLISH_DUE_INTERVAL_SECONDS,
        "options": {"queue": QUEUE_DEFAULT, "expires": PUBLISH_DUE_EXPIRES_SECONDS},
    },
}
