"""Own the GeoIP reader and bounded retention task for one app."""

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime

from simple_module_db import all_tenants, finalize_session, mark_written, tenant_context
from sqlalchemy import select

from sm_analytics.collection.retention import cleanup
from sm_analytics.core.geo import GeoResolver
from sm_analytics.core.settings import AnalyticsSettings
from sm_analytics.models import AnalyticsProperty

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    settings: AnalyticsSettings
    geo: GeoResolver = field(default_factory=GeoResolver)
    task: asyncio.Task | None = None

    async def sweep(self, factory) -> int:
        with all_tenants():
            async with factory() as db:
                tenants = (await db.scalars(select(AnalyticsProperty.tenant_id).distinct())).all()
        deleted = 0
        for tenant in tenants:
            with tenant_context(tenant):
                async with factory() as db:
                    deleted += await cleanup(
                        db,
                        tenant,
                        now=datetime.now(UTC),
                        retention_days=self.settings.retention_days,
                    )
                    mark_written(db)
                    await finalize_session(db)
        return deleted

    async def run(self, factory) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                await self.sweep(factory)
            except Exception:
                logger.exception("Analytics retention sweep failed")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        self.geo.close()
