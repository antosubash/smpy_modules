"""Celery app for the worker and beat processes (images, background_tasks).

The web process never imports this. Run it from the repo root, with ``host`` on
the path so ``-A worker:celery`` resolves; the Makefile targets (``make worker``,
``make beat`` ...) do that. ``build_runner_celery`` loads the same root ``.env``
and database-stored host settings the web process uses, so both read one
configuration (Redis URL, database, tenancy mode).
"""

from pathlib import Path

from background_tasks.runner import build_runner_celery

celery = build_runner_celery(Path(__file__).resolve().parent.parent / ".env")
