"""The pipeline's runtime in a Celery worker, which never builds the app.

* **Database** - the URL, tenancy policy and timeouts the framework's runner
  pinned on ``background_tasks.sync_db`` (from ``merge_host_settings``), spelled
  for the async driver. A per-process async engine on ``NullPool``: every task
  body runs on its own ``asyncio.run`` loop, and a pooled asyncpg connection
  belongs to the loop that opened it. Its session class gets the framework's
  entity listeners, the host's tenancy policy and images' own guard - without
  them the tenant bound around a task body would scope nothing. Rebuilt when
  that configuration changes and in a forked child (the parent's sockets are
  forgotten, never closed from the child).
* **Object intents** commit through this engine's factory
  (``intents.use_session_factory``).
* **Settings** - ``settings_for(ImagesSettings, "sm_images")`` (DB-backed, 30 s
  cache); **storage** - :func:`sm_images.storage.worker_store`; **bus** - the
  framework's worker bus (durable subscriptions of every installed module).
* **Registry** - ``load_extensions()`` on first use, the same code path as the
  web process's ``on_startup``.

:func:`run_task` is how a task body enters: refuse a running loop (an eager
``.delay()`` from async code would otherwise deadlock or skip the work), bind
the message's tenant - or, on a single-tenant host only, the configured default
- and run the coroutine to completion.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from sm_images.pipeline.runtime import Runtime

__all__ = [
    "reset_worker_runtime",
    "run_platform",
    "run_task",
    "task_tenant",
    "worker_runtime",
    "worker_session_factory",
    "worker_settings",
]

_lock = threading.Lock()
_engine: tuple[int, tuple[Any, ...], Any] | None = None  # (pid, config key, DatabaseState)


def _config() -> tuple[str, Any, dict[str, int]]:
    from background_tasks import sync_db

    return sync_db.async_database_url(), sync_db.engine_tenancy(), sync_db.database_options()


def worker_session_factory() -> Any:
    """This process's async session factory on the worker's database."""
    global _engine
    from simple_module_db import init_db
    from simple_module_db.listeners import attach_session_listeners
    from simple_module_db.query_filter import bind_engine_policy
    from sqlalchemy.pool import NullPool

    from sm_images import intents
    from sm_images.tenancy import install_guard

    url, policy, options = _config()
    key = (url, policy.tenant_strict, policy.default_tenant_id, tuple(sorted(options.items())))
    pid = os.getpid()
    with _lock:
        if _engine is not None and _engine[:2] == (pid, key):
            return _engine[2].session_factory
        _forget()
        state = init_db(
            url,
            poolclass=NullPool,
            connect_timeout=options.get("connect_timeout", 10),
            statement_timeout_ms=options.get("statement_timeout_ms", 0),
            idle_in_tx_timeout_ms=options.get("idle_in_tx_timeout_ms", 0),
        )
        attach_session_listeners(state.sync_session_class)
        bind_engine_policy(state.engine.sync_engine, policy)
        install_guard(state.sync_session_class)
        intents.use_session_factory(state.session_factory)
        _engine = (pid, key, state)
        return state.session_factory


def _forget() -> None:
    """Drop the cached engine. NullPool holds no idle connection, and a forked
    child must not close its parent's: ``close=False`` only forgets."""
    global _engine
    if _engine is not None:
        _engine[2].engine.sync_engine.dispose(close=_engine[0] == os.getpid())
    _engine = None


def reset_worker_runtime() -> None:
    """Forget the engine and the store (``worker_process_init``, tests)."""
    from sm_images.storage import reset_worker_store

    with _lock:
        _forget()
    reset_worker_store()


def worker_settings() -> Any:
    from background_tasks import settings_for

    from sm_images.constants import PACKAGE
    from sm_images.settings import ImagesSettings

    return settings_for(ImagesSettings, PACKAGE)


def _bus() -> Any:
    from background_tasks.outbox_worker import worker_bus

    return worker_bus()


def worker_runtime() -> Runtime:
    from sm_images.pipeline.extensions import load_extensions
    from sm_images.storage import worker_store

    load_extensions()
    return Runtime(
        session_factory=worker_session_factory(),
        store=worker_store,
        settings=worker_settings,
        bus=_bus,
    )


def task_tenant() -> str:
    """The tenant a task body runs in: the message's (restored by
    ``task_prerun``), else - single-tenant hosts only - the default."""
    from background_tasks import sync_db
    from simple_module_db.listeners import current_tenant_id

    from sm_images.tenancy import TenantUnbound

    tenant = current_tenant_id.get()
    if tenant:
        return tenant
    policy = sync_db.engine_tenancy()
    if policy.tenant_strict:
        raise TenantUnbound("an images task message carried no tenant (multi-tenant host)")
    return policy.default_tenant_id


def _no_running_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(
        "images task bodies start their own event loop and cannot run on a running one; "
        "from async code use sm_images.pipeline.orchestrate.submit_dispatch"
    )


def run_task[T](body: Callable[[Runtime, str], Awaitable[T]]) -> T:
    """Run a tenant-bound task body to completion on a fresh loop."""
    from simple_module_db import tenant_context

    _no_running_loop()
    tenant = task_tenant()
    runtime = worker_runtime()

    async def main() -> T:
        with tenant_context(tenant):
            return await body(runtime, tenant)

    return asyncio.run(main())


def run_platform[T](body: Callable[[Runtime], Awaitable[T]]) -> T:
    """Run a platform body (it enumerates tenants itself) with no tenant bound."""
    from simple_module_db import no_tenant

    _no_running_loop()
    runtime = worker_runtime()

    async def main() -> T:
        with no_tenant():
            return await body(runtime)

    return asyncio.run(main())
