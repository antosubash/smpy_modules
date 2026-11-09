"""Newsletter's runtime in a Celery worker, which never builds the app.

The database part of ``sm_images.pipeline.worker_runtime``, kept faithful to
it: the URL, tenancy policy and timeouts the framework's runner pinned on
``background_tasks.sync_db`` (from ``merge_host_settings``), spelled for the
async driver. A per-process async engine on ``NullPool``: every task body runs
on its own ``asyncio.run`` loop, and a pooled asyncpg connection belongs to the
loop that opened it. Its session class gets the framework's entity listeners,
the host's tenancy policy and newsletter's own guard - without them a tenant
bound inside a task body would scope nothing. Rebuilt when that configuration
changes and in a forked child (the parent's sockets are forgotten, never closed
from the child).

:func:`run_platform` is how a platform body (one that enumerates tenants
itself) enters: refuse a running loop (an eager ``.delay()`` from async code
would otherwise deadlock), unbind any tenant, run the coroutine to completion.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Awaitable, Callable
from typing import Any

__all__ = ["reset_worker_runtime", "run_platform", "worker_session_factory"]

_lock = threading.Lock()
_engine: tuple[int, tuple[Any, ...], Any] | None = None  # (pid, config key, DatabaseState)


def _config() -> tuple[str, Any, dict[str, int]]:
    from background_tasks.core import sync_db

    return sync_db.async_database_url(), sync_db.engine_tenancy(), sync_db.database_options()


def worker_session_factory() -> Any:
    """This process's async session factory on the worker's database."""
    global _engine
    from simple_module_db import init_db
    from simple_module_db.listeners import attach_session_listeners
    from simple_module_db.query_filter import bind_engine_policy
    from sqlalchemy.pool import NullPool

    from sm_newsletter.core.tenancy import install_guard

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
    """Forget the engine (``worker_process_init``, tests)."""
    with _lock:
        _forget()


def _no_running_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(
        "newsletter task bodies start their own event loop and cannot run on a running one; "
        "from async code await the coroutine (e.g. reconcile_async) directly"
    )


def run_platform[T](body: Callable[[Any], Awaitable[T]]) -> T:
    """Run a platform body (it enumerates tenants itself) with no tenant bound;
    ``body`` gets this process's session factory."""
    from simple_module_db import no_tenant

    _no_running_loop()
    factory = worker_session_factory()

    async def main() -> T:
        with no_tenant():
            return await body(factory)

    return asyncio.run(main())
