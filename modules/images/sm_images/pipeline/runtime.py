"""What the executor runs against: sessions, bytes, settings and the bus.

Two processes build one:

* the **web process** - images' ``on_startup`` calls :func:`use_runtime` with
  the app's session factory, its mounted storage backend, its hydrated
  settings and its event bus. Ingest's after-commit dispatch reads it here.
* a **Celery worker**, which never builds the app -
  :func:`sm_images.pipeline.worker_runtime.worker_runtime`.

Everything is a callable so a settings edit or a storage move is seen on the
next use, not frozen at boot.

``eager`` is ``None`` to ask Celery (``task_always_eager``) at each use. Eager
work is not sent through Celery at all: it is drained on the calling event loop
(:mod:`sm_images.pipeline.orchestrate`), because Celery's eager mode runs a
task body inside the publish, on the request's loop, where a task body's
``asyncio.run`` cannot run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

__all__ = ["Runtime", "celery_eager", "current_runtime", "use_runtime"]


def celery_eager() -> bool:
    """Whether the process's Celery app runs tasks inline (tests, dev without a broker)."""
    try:
        from celery import current_app
    except ImportError:  # pragma: no cover - background_tasks always brings celery
        return True
    return bool(current_app.conf.task_always_eager)


@dataclass(frozen=True)
class Runtime:
    session_factory: Any
    store: Callable[[], Any]
    settings: Callable[[], Any]
    bus: Callable[[], Any] = lambda: None
    eager: bool | None = None

    def is_eager(self) -> bool:
        return celery_eager() if self.eager is None else self.eager


_runtime: Runtime | None = None


def use_runtime(runtime: Runtime | None) -> None:
    """Set (or with ``None`` clear) the web process's runtime."""
    global _runtime
    _runtime = runtime


def current_runtime() -> Runtime | None:
    return _runtime
