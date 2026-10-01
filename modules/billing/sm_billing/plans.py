"""Plan CRUD and the invariants that keep entitlement resolution total.

Resolution always needs a default plan, so the service guarantees there is
exactly one, that it is free, and that it can be neither unset nor archived —
a new default is made by marking another free plan default. The session is
the caller's; nothing here commits.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sm_billing import constants as c
from sm_billing.models import Plan
from sm_billing.schemas import PlanIn

logger = logging.getLogger(__name__)


class PlanError(Exception):
    """A plan write that would break an invariant. ``code`` is the API detail."""

    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _check(data: PlanIn) -> None:
    has_price = bool(data.stripe_price_month or data.stripe_price_year)
    if data.pricing_model == c.PricingModel.FREE:
        if has_price:
            raise PlanError("free_plan_has_price")
        if data.trial_days:
            raise PlanError("free_plan_has_trial")
    elif not has_price:
        raise PlanError("paid_plan_needs_price")
    if data.is_default and data.pricing_model != c.PricingModel.FREE:
        raise PlanError("default_must_be_free")


class PlanService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(self, *, include_archived: bool = True) -> list[Plan]:
        stmt = select(Plan).order_by(Plan.sort_order, Plan.id)
        if not include_archived:
            stmt = stmt.where(Plan.archived_at.is_(None))
        return list((await self.db.execute(stmt)).scalars())

    async def get(self, plan_id: int) -> Plan | None:
        return await self.db.get(Plan, plan_id)

    async def by_key(self, key: str) -> Plan | None:
        return (await self.db.execute(select(Plan).where(Plan.key == key))).scalar_one_or_none()

    async def by_price(self, price_id: str) -> tuple[Plan, str] | None:
        stmt = select(Plan).where(
            or_(Plan.stripe_price_month == price_id, Plan.stripe_price_year == price_id)
        )
        plan = (await self.db.execute(stmt)).scalar_one_or_none()
        if plan is None:
            return None
        interval = c.Interval.MONTH if plan.stripe_price_month == price_id else c.Interval.YEAR
        return plan, interval

    async def default(self) -> Plan:
        stmt = select(Plan).where(Plan.is_default.is_(True)).limit(1)
        plan = (await self.db.execute(stmt)).scalar_one_or_none()
        if plan is None:  # pragma: no cover - startup seeds one and writes keep it
            raise PlanError("no_default_plan", status_code=500)
        return plan

    async def _ensure_unique(self, data: PlanIn, plan_id: int | None) -> None:
        existing = await self.by_key(data.key)
        if existing is not None and existing.id != plan_id:
            raise PlanError("plan_key_taken", status_code=409)
        for price in (data.stripe_price_month, data.stripe_price_year):
            if price is None:
                continue
            match = await self.by_price(price)
            if match is not None and match[0].id != plan_id:
                raise PlanError("price_taken", status_code=409)
        if data.stripe_price_month and data.stripe_price_month == data.stripe_price_year:
            raise PlanError("price_taken", status_code=409)

    async def _take_default(self, plan_id: int) -> None:
        await self.db.execute(
            update(Plan)
            .where(Plan.id != plan_id, Plan.is_default.is_(True))
            .values(is_default=False)
        )

    async def create(self, data: PlanIn) -> Plan:
        _check(data)
        await self._ensure_unique(data, None)
        plan = Plan(**data.model_dump())
        self.db.add(plan)
        await self.db.flush()
        if plan.is_default:
            await self._take_default(plan.id)
        return plan

    async def update(self, plan_id: int, data: PlanIn) -> Plan:
        plan = await self.get(plan_id)
        if plan is None:
            raise PlanError("plan_not_found", status_code=404)
        if data.key != plan.key:
            raise PlanError("plan_key_immutable")
        _check(data)
        if plan.is_default and not data.is_default:
            raise PlanError("default_required", status_code=409)
        if data.is_default and plan.archived_at is not None:
            raise PlanError("cannot_archive_default", status_code=409)
        await self._ensure_unique(data, plan.id)
        for field, value in data.model_dump().items():
            setattr(plan, field, value)
        plan.updated_at = datetime.now(UTC)
        await self.db.flush()
        if plan.is_default:
            await self._take_default(plan.id)
        return plan

    async def archive(self, plan_id: int) -> Plan:
        plan = await self.get(plan_id)
        if plan is None:
            raise PlanError("plan_not_found", status_code=404)
        if plan.is_default:
            raise PlanError("cannot_archive_default", status_code=409)
        if plan.archived_at is None:
            plan.archived_at = datetime.now(UTC)
            await self.db.flush()
        return plan


async def seed_default_plan(session_factory: async_sessionmaker) -> None:
    """Make sure a free default plan exists. Idempotent; runs at every startup."""
    async with session_factory() as session:
        default = (
            await session.execute(select(Plan).where(Plan.is_default.is_(True)).limit(1))
        ).scalar_one_or_none()
        if default is not None:
            return
        existing = (
            await session.execute(select(Plan).where(Plan.key == c.DEFAULT_PLAN_KEY))
        ).scalar_one_or_none()
        if existing is not None and existing.pricing_model == c.PricingModel.FREE:
            existing.is_default = True
            existing.archived_at = None
        else:
            key = c.DEFAULT_PLAN_KEY if existing is None else f"{c.DEFAULT_PLAN_KEY}-default"
            session.add(
                Plan(
                    key=key,
                    name=c.DEFAULT_PLAN_NAME,
                    pricing_model=c.PricingModel.FREE,
                    is_default=True,
                )
            )
        await session.commit()
        logger.info("billing: seeded the free default plan")
