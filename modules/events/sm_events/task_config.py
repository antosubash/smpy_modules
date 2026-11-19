"""Light Celery configuration, read by ``background_tasks`` without importing tasks.

* ``events`` - ``events.publish_due``, the beat every minute that publishes the
  events whose ``publish_at`` has come. A queued tick expires after 55 s, so a
  backlog (a stopped worker, a slow broker) is dropped rather than run late on
  top of the next tick: the next one picks the same rows up.

* ``events.run_import`` - one slice of an ``.ics`` import (re-enqueues itself while it answers
  ``more``); ``events.janitor`` - hourly: expires finished imports, relaunches lost work and
  removes revoked private feed links. The janitor's tick expires after 3,500 s for the same reason.

* ``events.reminders`` - the beat every minute that mails the reminders that have fallen due
  (:mod:`sm_events.reminders.tick`); a queued tick expires after 55 s, like ``publish_due``'s: a
  backlog is dropped, never run late, because a late reminder is worthless and the claim makes a
  doubled run harmless anyway.

``QUEUES`` is what a worker started for a queue subset
(``SM_BG_TASKS_WORKER_QUEUES``) checks before it imports ``sm_events.tasks``.
Beat lives here and only here, so the entry is never merged twice. A host
without beat never publishes on a schedule. Keep this file free of heavy
imports (and of celery).
"""

from __future__ import annotations

PUBLISH_DUE = "events.publish_due"
RUN_IMPORT = "events.run_import"
JANITOR = "events.janitor"
REMINDERS = "events.reminders"

QUEUE_DEFAULT = "events"
QUEUES = {QUEUE_DEFAULT}

TASK_ROUTES = {
    PUBLISH_DUE: {"queue": QUEUE_DEFAULT},
    RUN_IMPORT: {"queue": QUEUE_DEFAULT},
    JANITOR: {"queue": QUEUE_DEFAULT},
    REMINDERS: {"queue": QUEUE_DEFAULT},
}

PUBLISH_DUE_INTERVAL_SECONDS = 60.0
PUBLISH_DUE_EXPIRES_SECONDS = 55
JANITOR_INTERVAL_SECONDS = 3600.0
JANITOR_EXPIRES_SECONDS = 3500
REMINDERS_INTERVAL_SECONDS = 60.0
REMINDERS_EXPIRES_SECONDS = 55

BEAT_SCHEDULE = {
    "events-publish-due": {
        "task": PUBLISH_DUE,
        "schedule": PUBLISH_DUE_INTERVAL_SECONDS,
        "options": {"queue": QUEUE_DEFAULT, "expires": PUBLISH_DUE_EXPIRES_SECONDS},
    },
    "events-janitor": {
        "task": JANITOR,
        "schedule": JANITOR_INTERVAL_SECONDS,
        "options": {"queue": QUEUE_DEFAULT, "expires": JANITOR_EXPIRES_SECONDS},
    },
    "events-reminders": {
        "task": REMINDERS,
        "schedule": REMINDERS_INTERVAL_SECONDS,
        "options": {"queue": QUEUE_DEFAULT, "expires": REMINDERS_EXPIRES_SECONDS},
    },
}
