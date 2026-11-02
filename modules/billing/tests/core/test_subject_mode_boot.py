"""Boot-time behaviour of ``subject_mode`` (#274)."""

from __future__ import annotations

import dataclasses
import logging
from types import SimpleNamespace

import pytest
from simple_module_hosting.permissions import resolve_request_permissions
from sm_billing.core import constants as c
from sm_billing.core.subject_boot import apply_subject_mode
from sm_billing.models import Subscription
from sm_billing.plans.service import PlanService

STRANDED = "billing.subject_mode.stranded_default_rows"


def _set_mode(app, mode: str) -> None:
    getattr(app.state, c.PACKAGE).settings.subject_mode = mode


async def _user_permissions(app) -> set[str]:
    request = SimpleNamespace(
        state=SimpleNamespace(user=SimpleNamespace(roles=["user"], permissions=[], scopes=None)),
        app=app,
    )
    return await resolve_request_permissions(request, app.state.sm.permissions)


async def test_tenant_mode_is_default_and_inert(app, caplog):
    before = {k: set(v) for k, v in app.state.sm.permissions.role_map.items()}
    with caplog.at_level("WARNING"):
        await apply_subject_mode(app)
    assert app.state.billing_subject_mode == "tenant"
    assert {k: set(v) for k, v in app.state.sm.permissions.role_map.items()} == before
    assert not [r for r in caplog.records if "subject_mode" in r.message]


async def test_user_mode_refused_on_multi_tenant(app):
    _set_mode(app, "user")
    with pytest.raises(RuntimeError, match="needs a single-tenant host"):
        await apply_subject_mode(app)


async def test_user_mode_grants_view_and_manage_to_user_role(single_tenant, app):
    assert c.PERM_MANAGE not in await _user_permissions(app)
    _set_mode(app, "user")
    await apply_subject_mode(app)
    assert app.state.billing_subject_mode == "user"
    held = await _user_permissions(app)
    assert {c.PERM_VIEW, c.PERM_MANAGE} <= held


async def test_stranded_default_rows_warn(single_tenant, app, caplog):
    async with app.state.sm.db.session_factory() as session:
        plan = await PlanService(session).default()
        session.add(Subscription(tenant_id="default", plan_id=plan.id))
        await session.commit()
    _set_mode(app, "user")
    with caplog.at_level("WARNING"):
        await apply_subject_mode(app)
    assert [r for r in caplog.records if STRANDED in r.message]
    assert len(_boot_warnings(caplog)) == 1


def _module_from(package: str):
    """A stand-in module instance whose package is ``package``."""
    return type("StubModule", (), {"__module__": f"{package}.module"})()


def _boot_warnings(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "sm_billing.core.subject_boot" and r.levelno >= logging.WARNING
    ]


@pytest.mark.parametrize("stranded", [False, True])
async def test_user_mode_boot_warns_only_about_stranded_rows(
    single_tenant, app, caplog, monkeypatch, stranded
):
    """Images and ai bill the user now (#284): with both installed, user-mode boot
    logs no warning but the documented stranded-rows one, however it is worded."""
    modules = [*app.state.sm.modules, _module_from("sm_images"), _module_from("sm_ai")]
    monkeypatch.setattr(app.state, "sm", dataclasses.replace(app.state.sm, modules=modules))
    if stranded:
        async with app.state.sm.db.session_factory() as session:
            session.add(_stranded_row("gauge"))
            await session.commit()
    _set_mode(app, "user")
    with caplog.at_level("WARNING"):
        await apply_subject_mode(app)
    warnings = _boot_warnings(caplog)
    assert len(warnings) == int(stranded)
    assert all(STRANDED in w for w in warnings)


def _stranded_row(kind: str):
    from sm_billing.models import Customer, UsageGauge, UsageHold

    if kind == "gauge":
        return UsageGauge(tenant_id="default", meter="files.storage", in_use=1)
    if kind == "hold":
        return UsageHold(
            id="h1",
            tenant_id="default",
            meter="files.storage",
            quantity=1,
            status="held",
            idempotency_key="k",
            source="test",
        )
    return Customer(tenant_id="default", provider="stripe", provider_customer_id="cus_1")


@pytest.mark.parametrize("kind", ["gauge", "hold", "customer"])
async def test_every_stranded_default_row_warns(single_tenant, app, caplog, kind):
    async with app.state.sm.db.session_factory() as session:
        session.add(_stranded_row(kind))
        await session.commit()
    _set_mode(app, "user")
    with caplog.at_level("WARNING"):
        await apply_subject_mode(app)
    assert [r for r in caplog.records if STRANDED in r.message]
