"""Work a request asks for but must not start until its transaction is gone.

FastAPI's ``BackgroundTasks`` is the obvious home for the reindex of §8.9 and
is the wrong one, for a reason that is entirely about ordering rather than
about background work. A route's ``Depends`` teardown is registered on the
``AsyncExitStack`` ``fastapi.routing.request_response`` opens *around* the
response::

    async with AsyncExitStack() as request_stack:      # get_db's exit lives here
        response = await handler(request)
        await response(scope, receive, send)           # <- background tasks run HERE
    # <- only now does get_db commit and release the session

So a background task runs while the request's own session still holds its
transaction open, and the request cannot commit until the task returns. On
Postgres that is merely a stale read; on SQLite it is a deadlock the database
breaks by returning ``database is locked`` after the driver's busy timeout —
the rebuild's first ``DELETE`` waits on a ``RESERVED`` lock that only the
request can drop, and the request is waiting on the rebuild.

Middleware is the first place that is genuinely *after* that exit stack: the
user middleware stack wraps the router, so ``await self.app(...)`` returns only
once every dependency has torn down and ``get_db`` has committed. The job list
rides on ``scope`` so a handler can add to it with nothing but its ``Request``.

**A job runs in the tenant that queued it** (tenancy design §A.5). Running
after the exit stack also means running outside ``TenantMiddleware`` and
outside records' own binding, and both have reset ``current_tenant_id`` by the
time the drain runs (FACT 2″). Left alone, a job would run unbound: a type
write's reindex would load its type under no filter, or the wrong one, and
quietly rebuild nothing. So :func:`defer` captures
:func:`~sm_records.tenancy.bound_tenant` when the job is queued, and wraps the
job in :func:`~sm_records.tenancy.tenant_scope`. Queuing a job with no tenant
bound is a bug in the caller, so :func:`defer` raises
:class:`~sm_records.tenancy.TenantUnbound` at that point. The alternative is a
failure in the drain, where it only reaches a log.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Final

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from sm_records.tenancy import bound_tenant, tenant_scope

__all__ = ["SCOPE_KEY", "DeferredJobsMiddleware", "defer"]

logger = logging.getLogger(__name__)

SCOPE_KEY: Final = "sm_records.deferred_jobs"
"""``scope`` key holding this request's job list — present only while
:class:`DeferredJobsMiddleware` is installed, which is what :func:`defer`
tests for."""

Job = Callable[[], Awaitable[object]]
"""A zero-argument coroutine *factory* — ``functools.partial(coro_fn, ...)``.

Not a coroutine object: a job that is never run (the request raised) would
then be a ``coroutine was never awaited`` warning pointing at this module
rather than at whatever actually failed.
"""

#: Strong references to detached fallback tasks. ``asyncio`` keeps only a weak
#: one, so a task nothing holds can be collected mid-await.
_orphans: set[asyncio.Task] = set()


async def _in_tenant(tenant: str, job: Job) -> object:
    """Run ``job`` bound to the tenant that queued it.

    :func:`tenant_scope` re-enters a tenant that is already bound. That
    happens when the drain runs inside a binding of its own, such as a test
    task or a single-mode harness. A *different* tenant is refused: a job must
    never run as another tenant.
    """
    with tenant_scope(tenant):
        return await job()


def defer(request: Request, job: Job) -> None:
    """Run ``job`` once this request's session has been committed and closed.

    With the middleware installed — which :meth:`RecordsModule.register_middleware
    <sm_records.module.RecordsModule.register_middleware>` does — the job is
    queued on ``scope`` and awaited there. Without it (a host that mounted the
    routers by hand, a harness) the job is detached onto the event loop
    instead: it still will not deadlock the request, because nothing awaits it,
    but it may start before the commit lands, so the case is logged.

    Either way, the job runs in the tenant bound when :func:`defer` is called
    (see the module docstring).
    """
    job = partial(_in_tenant, bound_tenant(), job)
    jobs = request.scope.get(SCOPE_KEY)
    if jobs is None:
        logger.warning(
            "records: DeferredJobsMiddleware is not installed; running a deferred job detached"
        )
        task = asyncio.get_running_loop().create_task(job())
        _orphans.add(task)
        task.add_done_callback(_orphans.discard)
        return
    jobs.append(job)


class DeferredJobsMiddleware:
    """Drains what :func:`defer` queued, after the route tore its session down.

    Pure ASGI rather than ``BaseHTTPMiddleware`` because the only thing it
    needs is the point in time *after* ``self.app`` returns, and
    ``BaseHTTPMiddleware`` buys a task group and a stream to reach the same
    point. The response has already been sent by then, so the client waits for
    none of this — exactly as it would not wait for a background task.

    A request that raised runs nothing: the writes a job was queued for went
    back with it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        scope[SCOPE_KEY] = []
        try:
            await self.app(scope, receive, send)
        except BaseException:
            scope.pop(SCOPE_KEY, None)
            raise
        for job in scope.pop(SCOPE_KEY, []):
            try:
                await job()
            except Exception:  # pragma: no cover - jobs log their own failures
                logger.exception("records: deferred job failed")
