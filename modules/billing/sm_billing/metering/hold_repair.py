"""``recount``: the admin repair for a gauge whose level drifted from its holds.

A base of ``HoldsMixin``, split out of ``holds`` to keep it under the size cap.
Like every hold write it is its own short transaction (``metering.tx``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sm_billing.contracts.metering import MeterKind
from sm_billing.metering import hold_sql
from sm_billing.metering.core import MeteringCore
from sm_billing.metering.tx import Counted, run_write
from sm_billing.metering.validate import check_text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class HoldRepairMixin(MeteringCore):
    async def recount(self, tenant_id: str, meter: str) -> int:
        """Rebuild the level from the live (held and committed) holds; returns it.

        The admin repair for drift (a bug that bypassed the service). Lapsed
        holds the sweeper has not expired yet still count, as they do in the
        gauge until it does.
        """
        check_text("tenant_id", tenant_id, 32)
        self._require(meter, MeterKind.GAUGE)
        now = self._clock()
        fields = {"tenant_id": tenant_id, "meter": meter, "now": now}

        async def apply(session: AsyncSession) -> Counted:
            dialect = session.get_bind().dialect.name
            await session.execute(hold_sql.touch_gauge(dialect, **fields))
            level = (await session.execute(hold_sql.recount(**fields))).scalar_one()
            return Counted(int(level))

        outcome = await run_write(self._factory, None, apply)
        return outcome.used
