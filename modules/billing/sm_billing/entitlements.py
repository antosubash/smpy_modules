"""``PlanEntitlements`` — the tenants entitlement seam, answered from plans.

Installed as ``app.state.tenants.entitlements`` at startup. ``tenants`` reads
that attribute per request, so consumers keep depending on its protocol and
never import billing. Each call opens its own short session: callers (the
tenants service, a consumer's route) hold their own and must not see ours.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker

from sm_billing.resolve import effective_plan


class PlanEntitlements:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def limit(self, tenant_id: str, key: str) -> int | None:
        """The plan's limit for ``key``; an absent key is unlimited (``None``)."""
        async with self._session_factory() as session:
            plan, _ = await effective_plan(session, tenant_id)
        value = plan.limits.get(key)
        return None if value is None else int(value)

    async def has_feature(self, tenant_id: str, key: str) -> bool:
        async with self._session_factory() as session:
            plan, _ = await effective_plan(session, tenant_id)
        return key in plan.features
