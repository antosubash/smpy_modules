from __future__ import annotations

import pytest
from sm_billing.constants import DEFAULT_PLAN_KEY, PricingModel
from sm_billing.models import Plan
from sm_billing.plans import PlanError, PlanService, seed_default_plan
from sm_billing.schemas import PlanIn
from sqlalchemy import func, select


def _paid(key: str = "team", **kw) -> PlanIn:
    data = {
        "key": key,
        "name": key.title(),
        "pricing_model": "flat",
        "currency": "eur",
        "stripe_price_month": f"price_{key}",
    }
    data.update(kw)
    return PlanIn(**data)


async def _service(app):
    session = app.state.sm.db.session_factory()
    return session, PlanService(session)


async def test_startup_seeds_one_free_default(app):
    async with app.state.sm.db.session_factory() as session:
        plan = await PlanService(session).default()
        assert plan.key == DEFAULT_PLAN_KEY
        assert plan.pricing_model == PricingModel.FREE
        assert plan.is_default


async def test_seed_is_idempotent(app):
    await seed_default_plan(app.state.sm.db.session_factory)
    async with app.state.sm.db.session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(Plan))).scalar_one()
    assert count == 1


async def test_create_paid_plan(app):
    session, svc = await _service(app)
    async with session:
        plan = await svc.create(_paid(limits={"tenants.seats": 5}, features=["sso"]))
        assert plan.id is not None
        assert plan.limits == {"tenants.seats": 5}


@pytest.mark.parametrize(
    ("data", "code"),
    [
        ({"pricing_model": "free", "stripe_price_month": "p"}, "free_plan_has_price"),
        (
            {"pricing_model": "free", "stripe_price_month": None, "trial_days": 7},
            "free_plan_has_trial",
        ),
        ({"stripe_price_month": None}, "paid_plan_needs_price"),
        ({"is_default": True}, "default_must_be_free"),
    ],
)
async def test_plan_invariants(app, data, code):
    session, svc = await _service(app)
    async with session:
        with pytest.raises(PlanError) as exc:
            await svc.create(_paid(**data))
        assert exc.value.code == code


async def test_key_and_price_unique(app):
    session, svc = await _service(app)
    async with session:
        await svc.create(_paid("team"))
        with pytest.raises(PlanError) as exc:
            await svc.create(_paid("team", stripe_price_month="other"))
        assert exc.value.code == "plan_key_taken"
        with pytest.raises(PlanError) as exc:
            await svc.create(_paid("pro", stripe_price_month="price_team"))
        assert exc.value.code == "price_taken"


async def test_new_default_replaces_old(app):
    session, svc = await _service(app)
    async with session:
        old = await svc.default()
        new = await svc.create(
            PlanIn(key="starter", name="Starter", pricing_model="free", is_default=True)
        )
        await session.flush()
        assert (await svc.default()).id == new.id
        await session.refresh(old)
        assert old.is_default is False


async def test_default_cannot_be_unset_or_archived(app):
    session, svc = await _service(app)
    async with session:
        default = await svc.default()
        data = PlanIn(key=default.key, name="Free", pricing_model="free", is_default=False)
        with pytest.raises(PlanError) as exc:
            await svc.update(default.id, data)
        assert exc.value.code == "default_required"
        with pytest.raises(PlanError) as exc:
            await svc.archive(default.id)
        assert exc.value.code == "cannot_archive_default"


async def test_key_is_immutable(app):
    session, svc = await _service(app)
    async with session:
        plan = await svc.create(_paid("team"))
        with pytest.raises(PlanError) as exc:
            await svc.update(plan.id, _paid("renamed"))
        assert exc.value.code == "plan_key_immutable"


async def test_by_price_maps_interval(app):
    session, svc = await _service(app)
    async with session:
        await svc.create(_paid("team", stripe_price_year="price_team_y"))
        plan, interval = await svc.by_price("price_team_y")
        assert (plan.key, interval) == ("team", "year")
        assert await svc.by_price("nope") is None


def test_plan_in_normalises_blank_prices_and_currency():
    data = PlanIn(key="x", name="X", pricing_model="free", stripe_price_month="  ", currency="EUR")
    assert data.stripe_price_month is None
    assert data.currency == "eur"


@pytest.mark.parametrize("key", ["Bad Key", "-x", "", "x" * 65])
def test_plan_in_rejects_bad_keys(key):
    with pytest.raises(ValueError):
        PlanIn(key=key, name="X", pricing_model="free")


def test_plan_in_rejects_negative_limits():
    with pytest.raises(ValueError):
        PlanIn(key="x", name="X", pricing_model="free", limits={"tenants.seats": -1})
