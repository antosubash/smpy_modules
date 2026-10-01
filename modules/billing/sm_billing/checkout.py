"""What a tenant owner can do: see status, check out, open the portal, change plan.

Nothing here grants a plan. Checkout returns a Stripe URL and the webhook
writes the subscription; plan changes call the provider and then re-sync from
its answer, so the local row always mirrors what Stripe actually did.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from sm_billing import constants as c
from sm_billing.contracts.provider import ProviderError
from sm_billing.errors import BillingError
from sm_billing.lifecycle import tenant_service
from sm_billing.models import Customer, Plan, Subscription
from sm_billing.plans import PlanService
from sm_billing.resolve import effective_plan, subscription_for
from sm_billing.schemas import PlanOut, StatusOut, SubscriptionOut
from sm_billing.sync import apply_snapshot

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from sm_billing.contracts.provider import BillingProvider


def plan_out(plan: Plan) -> PlanOut:
    return PlanOut.model_validate(plan, from_attributes=True)


def subscription_out(sub: Subscription | None) -> SubscriptionOut | None:
    if sub is None:
        return None
    return SubscriptionOut(
        status=sub.status,
        interval=sub.interval,
        quantity=sub.quantity,
        trial_end=sub.trial_end,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=sub.cancel_at_period_end,
        has_provider_subscription=sub.provider_subscription_id is not None,
    )


class BillingService:
    def __init__(self, db: AsyncSession, app: FastAPI, tenant_id: str) -> None:
        self.db = db
        self.app = app
        self.tenant_id = tenant_id
        services = getattr(app.state, c.PACKAGE)
        self.provider: BillingProvider = services.provider
        self.plans = PlanService(db)
        self.tenants = tenant_service(db, app)

    # ── reads ───────────────────────────────────────────────────

    async def members(self) -> int:
        return (await self.tenants.member_counts([self.tenant_id])).get(self.tenant_id, 0)

    async def status(self) -> StatusOut:
        plan, sub = await effective_plan(self.db, self.tenant_id)
        customer = await self.db.get(Customer, self.tenant_id)
        return StatusOut(
            plan=plan_out(plan),
            subscription=subscription_out(sub),
            seats={"used": await self.members(), "limit": plan.limits.get(c.ENTITLEMENT_SEATS)},
            provider=self.provider.name,
            checkout_available=self.provider.supports_checkout,
            portal_available=self.provider.supports_checkout
            and customer is not None
            and customer.provider_customer_id is not None,
        )

    async def public_plans(self) -> list[PlanOut]:
        plans = await self.plans.list(include_archived=False)
        return [plan_out(p) for p in plans if p.is_public]

    # ── guards ──────────────────────────────────────────────────

    def _require_checkout(self) -> None:
        if not self.provider.supports_checkout:
            raise BillingError("checkout_unavailable", 409)

    async def _target(self, plan_id: int) -> Plan:
        plan = await self.plans.get(plan_id)
        if plan is None or plan.archived_at is not None or not plan.is_public:
            raise BillingError("plan_not_found", 404)
        return plan

    @staticmethod
    def _price(plan: Plan, interval: str) -> str:
        price = plan.stripe_price_month if interval == c.Interval.MONTH else plan.stripe_price_year
        if not price:
            raise BillingError("interval_unavailable")
        return price

    async def _seat_guard(self, plan: Plan) -> None:
        limit = plan.limits.get(c.ENTITLEMENT_SEATS)
        used = await self.tenants.seats_used(self.tenant_id)
        if limit is not None and used > limit:
            raise BillingError("too_many_members", 409, used=used, limit=limit)

    async def _quantity(self, plan: Plan) -> int:
        if plan.pricing_model == c.PricingModel.PER_SEAT:
            return max(1, await self.members())
        return 1

    async def _live_subscription(self) -> Subscription | None:
        sub = await subscription_for(self.db, self.tenant_id)
        if sub is None or sub.provider_subscription_id is None:
            return None
        return sub if sub.status in c.ENTITLED_STATUSES else None

    async def _resync(self, subscription_id: str) -> None:
        snapshot = await self.provider.fetch_subscription(subscription_id)
        await apply_snapshot(self.db, self.app, snapshot, provider=self.provider.name)

    # ── writes ──────────────────────────────────────────────────

    async def checkout(self, plan_id: int, interval: str, *, email: str | None, base: str) -> str:
        self._require_checkout()
        plan = await self._target(plan_id)
        if plan.pricing_model == c.PricingModel.FREE:
            raise BillingError("plan_is_free")
        price = self._price(plan, interval)
        if await self._live_subscription() is not None:
            raise BillingError("already_subscribed", 409)
        await self._seat_guard(plan)
        customer = await self._customer(email)
        # The local row only changes when a webhook lands, so ask Stripe too:
        # a subscription paid in another tab must not be joined by a second.
        if await self.provider.live_subscription_ids(customer.provider_customer_id):
            raise BillingError("already_subscribed", 409)
        if customer.checkout_session_id:
            # One open session per tenant: the older one can no longer be paid.
            with contextlib.suppress(ProviderError):  # already completed or expired
                await self.provider.expire_checkout(customer.checkout_session_id)
        session = await self.provider.create_checkout(
            customer_id=customer.provider_customer_id,
            price_id=price,
            quantity=await self._quantity(plan),
            trial_days=0 if await self._trial_used() else plan.trial_days,
            tenant_id=self.tenant_id,
            success_url=f"{base}{c.VIEW_PREFIX}/?checkout=success",
            cancel_url=f"{base}{c.VIEW_PREFIX}/?checkout=cancel",
        )
        customer.checkout_session_id = session.id
        await self.db.flush()
        return session.url

    async def _customer(self, email: str | None) -> Customer:
        customer = await self.db.get(Customer, self.tenant_id)
        if customer is not None and customer.provider_customer_id is not None:
            return customer
        tenant = await self.tenants.get(self.tenant_id)
        customer_id = await self.provider.ensure_customer(
            self.tenant_id, tenant.name if tenant else self.tenant_id, email
        )
        if customer is None:
            customer = Customer(tenant_id=self.tenant_id, provider=self.provider.name)
            self.db.add(customer)
        customer.provider_customer_id = customer_id
        customer.provider = self.provider.name
        customer.email = email
        await self.db.flush()
        return customer

    async def _trial_used(self) -> bool:
        """One trial per organisation: any earlier provider subscription spent it."""
        sub = await subscription_for(self.db, self.tenant_id)
        return sub is not None and (
            sub.provider_subscription_id is not None or sub.trial_end is not None
        )

    async def portal(self, *, base: str) -> str:
        self._require_checkout()
        customer = await self.db.get(Customer, self.tenant_id)
        if customer is None or customer.provider_customer_id is None:
            raise BillingError("no_customer", 409)
        return await self.provider.portal_url(
            customer.provider_customer_id, f"{base}{c.VIEW_PREFIX}/"
        )

    async def change_plan(self, plan_id: int, interval: str) -> StatusOut:
        self._require_checkout()
        plan = await self._target(plan_id)
        sub = await self._live_subscription()
        if sub is None:
            raise BillingError("no_subscription", 409)
        await self._seat_guard(plan)
        subscription_id = sub.provider_subscription_id
        if plan.pricing_model == c.PricingModel.FREE:
            await self.provider.cancel_at_period_end(subscription_id)
        else:
            price = self._price(plan, interval)
            if sub.plan_id == plan.id and sub.interval == interval and not sub.cancel_at_period_end:
                raise BillingError("already_on_plan", 409)
            await self.provider.change_plan(subscription_id, price, await self._quantity(plan))
        await self._resync(subscription_id)
        return await self.status()
