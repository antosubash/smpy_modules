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

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

__all__ = [
    "Runtime",
    "bind_runtime",
    "celery_eager",
    "current_runtime",
    "use_runtime",
    "worker_multi_tenant",
]


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
    multi_tenant: Callable[[], bool] | None = None
    """The host's tenancy mode: the framework's in the web process, the worker
    engine's policy in a worker (:func:`worker_multi_tenant`). Never inferred
    from a tenant id; an unknown mode is multi-tenant (fail closed)."""
    maps: bool = True
    """Whether this runtime hands map builds off (``sm_images.map.schedule``).
    Changes are counted either way; a test pipeline turns hand-offs off so a
    test that is not about the map never runs tippecanoe."""

    def is_eager(self) -> bool:
        return celery_eager() if self.eager is None else self.eager

    def is_multi_tenant(self) -> bool:
        if self.multi_tenant is not None:
            return bool(self.multi_tenant())
        return worker_multi_tenant()


def worker_multi_tenant() -> bool:
    """The worker engine's ``tenant_strict`` (it mirrors the host's
    ``multi_tenant``) - or ``True`` when there is no policy to read: the engine
    was never configured (``set_database_url`` not called; read from the
    framework's ``_url_override``, so its disappearance also fails closed), the
    policy cannot be built, or it does not say."""
    try:
        from background_tasks import sync_db

        if getattr(sync_db, "_url_override", None) is None:
            return True
        strict = getattr(sync_db.engine_tenancy(), "tenant_strict", None)
    except Exception:
        return True
    return True if strict is None else bool(strict)


_runtime: Runtime | None = None
_bound: ContextVar[Runtime | None] = ContextVar("sm_images_bound_runtime", default=None)


def use_runtime(runtime: Runtime | None) -> None:
    """Set (or with ``None`` clear) the web process's runtime."""
    global _runtime
    _runtime = runtime


@contextmanager
def bind_runtime(runtime: Runtime) -> Iterator[Runtime]:
    """Make ``runtime`` the current one for this context (a task body, an import
    run), so ingest's after-commit dispatch inside it - which has no runtime of
    its own in a worker - plans through it rather than waiting for reconcile."""
    token = _bound.set(runtime)
    try:
        yield runtime
    finally:
        _bound.reset(token)


def current_runtime() -> Runtime | None:
    return _bound.get() or _runtime
