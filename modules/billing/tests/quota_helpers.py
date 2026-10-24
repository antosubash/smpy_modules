"""Test routes guarded by ``RequiresQuota`` and a plan that limits them.

Behind the ``quota_app``, ``runs`` and ``owner`` fixtures in ``conftest``.
"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from helpers import make_plan
from sm_billing.constants import METERS_STATE_ATTR
from sm_billing.metering.deps import RequiresQuota
from sm_billing.models import Subscription
from usage_helpers import METER

PREFIX = "/api/quota-test"


def route(app, path: str, endpoint) -> None:
    """Add a test route ahead of the host's catch-alls."""
    app.add_api_route(f"{PREFIX}{path}", endpoint, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())


def install_quota_routes(app):
    getattr(app.state, METERS_STATE_ATTR).define(key=METER, kind="counter")

    async def ok(outcome=RequiresQuota(METER)):
        return {"used": outcome.used, "replayed": outcome.replayed}

    async def boom(_=RequiresQuota(METER)):
        raise HTTPException(418, "teapot")

    async def soft_fail(_=RequiresQuota(METER)):
        return JSONResponse({"detail": "nope"}, status_code=422)

    async def count(outcome=RequiresQuota(METER)):
        app.state.quota_runs.append(1)
        return {"used": outcome.used}

    async def count_boom(_=RequiresQuota(METER)):
        app.state.quota_runs.append(1)
        raise HTTPException(418, "teapot")

    app.state.quota_runs = []
    route(app, "/count", count)
    route(app, "/count-boom", count_boom)
    route(app, "/ok", ok)
    route(app, "/boom", boom)
    route(app, "/soft", soft_fail)
    return app


async def limit_plan(app, tenant_id: str, limit: int) -> None:
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, "metered", limits={METER: limit})
        session.add(Subscription(tenant_id=tenant_id, plan_id=plan.id))
        await session.commit()
