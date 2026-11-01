"""Re-pull every provider subscription; the safety net for missed webhooks.

Safe to run live and to run twice: each tenant is one fetch → ``apply_snapshot``
→ quantity push, the same path a webhook takes. A failure for one tenant is
recorded and the run moves on.

This is the whole-estate run behind ``smpy billing reconcile``. The periodic
loop (``reconcile_interval_minutes``) drives the same ``reconcile_one`` from
:mod:`sm_billing.scheduler`, over only the subscriptions gone stale.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from simple_module_db import finalize_session, tenant_context
from sqlalchemy import select

from sm_billing import constants as c
from sm_billing.lifecycle import tenant_gone
from sm_billing.models import Subscription
from sm_billing.seats import push_quantity
from sm_billing.services import current_provider
from sm_billing.subjects import tenant_of
from sm_billing.sweep import run_teardown, sweep_deleted_tenants
from sm_billing.sync import resync

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


@dataclass
class ReconcileReport:
    synced: int = 0
    pushed: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    skipped: str = ""
    #: Deleted tenants whose provider leftovers the sweep canceled.
    torn_down: int = 0


async def _targets(app: FastAPI, tenant_id: str | None) -> list[tuple[str, str]]:
    async with app.state.sm.db.session_factory() as session:
        stmt = select(Subscription.tenant_id, Subscription.provider_subscription_id).where(
            Subscription.provider_subscription_id.is_not(None)
        )
        if tenant_id is not None:
            stmt = stmt.where(Subscription.tenant_id == tenant_id)
        return [(t, s) for t, s in (await session.execute(stmt)).all()]


async def reconcile_one(app: FastAPI, tenant_id: str, subscription_id: str) -> bool:
    """Sync one tenant from the provider; returns whether a quantity was pushed.

    Runs bound to the subject's tenant: nothing outside a request binds one,
    and the ``TenantStatusChanged`` handlers ``finalize_session`` runs may read
    tenant-scoped tables of other modules, which are unfiltered while unbound.
    A user subject (``user:<id>``) lives under ``"default"``, never its own id.
    """
    provider = current_provider(app)
    with tenant_context(tenant_of(tenant_id)):
        async with app.state.sm.db.session_factory() as session:
            deleted = await tenant_gone(session, app, tenant_id)
            if not deleted:
                await resync(session, app, provider, subscription_id)
                await finalize_session(session)
        if deleted:
            # The ``TenantDeleted`` cancel may have failed: cancel rather than
            # keep mirroring a subscription nobody owns (``sm_billing.teardown``).
            await run_teardown(app, tenant_id)  # due check and failure bookkeeping
            return False
        return await push_quantity(app, tenant_id)


async def reconcile(app: FastAPI, *, tenant_id: str | None = None) -> ReconcileReport:
    report = ReconcileReport()
    provider = getattr(app.state, c.PACKAGE).provider
    if provider is None or not provider.supports_checkout:
        report.skipped = f"{getattr(provider, 'name', 'no')} provider"
        return report
    targets = await _targets(app, tenant_id)
    for target_tenant, subscription_id in targets:
        try:
            pushed = await reconcile_one(app, target_tenant, subscription_id)
        except Exception as exc:
            logger.warning("billing: reconcile failed for tenant %s", target_tenant, exc_info=True)
            report.errors.append((target_tenant, f"{type(exc).__name__}: {exc}"))
            continue
        report.synced += 1
        report.pushed += int(pushed)
    await sweep_deleted_tenants(app, report, tenant_id=tenant_id, attempted={t for t, _ in targets})
    return report
