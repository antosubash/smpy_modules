"""Boot-time behaviour of ``subject_mode`` (#274)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from simple_module_hosting.permissions import resolve_request_permissions
from sm_billing import constants as c
from sm_billing.models import Subscription
from sm_billing.plans import PlanService
from sm_billing.subject_boot import apply_subject_mode

STRANDED = "billing.subject_mode.stranded_default_rows"
CALLERS = "billing.subject_mode.tenant_billed_callers"


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
    assert [r for r in caplog.records if CALLERS in r.message] == []


async def test_installed_images_or_ai_warn(single_tenant, app, caplog, monkeypatch):
    from sm_billing import subject_boot

    monkeypatch.setattr(subject_boot, "installed_callers", lambda _app: ["images", "ai"])
    _set_mode(app, "user")
    with caplog.at_level("WARNING"):
        await apply_subject_mode(app)
    [rec] = [r for r in caplog.records if CALLERS in r.message]
    assert "images" in rec.getMessage() and "ai" in rec.getMessage()
