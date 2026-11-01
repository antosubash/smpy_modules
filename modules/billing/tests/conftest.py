"""Shared fixtures for the billing tests.

The app is the real one: ``simple_module_test``'s ``app`` fixture builds it
with ``create_app`` over the installed modules, restricted here to billing and
what it stands on, so a test exercises the same tenants resolver, permission
mapping and entitlement seam a host does. SQLite in memory unless
``SM_TEST_DATABASE_URL`` names a Postgres database.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from simple_module_hosting.settings import Settings
from simple_module_test.database import database_url_for_tests
from simple_module_test.session_cookie import forge_session_cookie
from sqlalchemy import select

MODULES = ["Auth", "Users", "Permissions", "Settings", "Tenants", "Billing"]
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _project_root(monkeypatch):
    """``create_app`` finds the Inertia host templates under the project root,
    resolved once at import from the cwd. CI runs this suite from
    ``modules/billing``, so point it at the repo root (``host/templates``)."""
    from simple_module_hosting import app_builder

    monkeypatch.setattr(app_builder, "_PROJECT_ROOT", REPO_ROOT)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url=database_url_for_tests(),
        environment="testing",
        secret_key="test-secret-key",
        multi_tenant=True,
        tenant_header="X-Tenant-ID",
        auth_provider="users",
        modules_enabled=MODULES,
    )


@pytest.fixture
def single_tenant(settings) -> Settings:
    """A single-tenant host: what ``subject_mode = "user"`` requires."""
    settings.multi_tenant = False
    return settings


@pytest.fixture
async def user_mode_app(single_tenant, app):
    """The app in ``subject_mode = "user"``: billing bills the signed-in user.

    The mode is applied the way ``on_startup`` applies it, after the setting is
    in place (the app fixture has already run startup in tenant mode).
    """
    from sm_billing import constants as c
    from sm_billing.subject_boot import apply_subject_mode

    getattr(app.state, c.PACKAGE).settings.subject_mode = c.SUBJECT_MODE_USER
    await apply_subject_mode(app)
    return app


@pytest.fixture(autouse=True)
def _fresh_membership_cache():
    from tenants.resolver import forget

    forget(None)
    yield
    forget(None)


@pytest.fixture
def status_events(app) -> list[str]:
    """Every ``TenantStatusChanged`` published, as its new status.

    The event is queued on ``on_commit`` and only ``finalize_session`` drains
    it, so a path that commits with a bare ``commit()`` leaves this empty.
    """
    from tenants.contracts.events import TenantStatusChanged

    seen: list[str] = []

    async def record(event: TenantStatusChanged) -> None:
        seen.append(event.status)

    app.state.sm.event_bus.subscribe(TenantStatusChanged, record)
    return seen


async def make_user(app, email: str) -> str:
    from users.models import Role, User, UserRole

    async with app.state.sm.db.session_factory() as session:
        user = User(
            id=uuid.uuid4(),
            email=email,
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        session.add(user)
        await session.flush()
        role = (await session.execute(select(Role).where(Role.name == "user"))).scalar_one_or_none()
        if role is not None:
            session.add(UserRole(user_id=user.id, role_id=role.id))
        await session.commit()
        return str(user.id)


@pytest.fixture
def user_client(app) -> Callable:
    """``async with user_client("a@x.io") as (client, user_id): ...``"""

    @asynccontextmanager
    async def factory(email: str) -> AsyncIterator[tuple[httpx.AsyncClient, str]]:
        user_id = await make_user(app, email)
        cookie = forge_session_cookie(app.state.sm.settings.secret_key, {"user_id": user_id})
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            cookies={"session": cookie},
        ) as client:
            yield client, user_id

    return factory


@pytest.fixture
def quota_app(app):
    """The app with ``quota_helpers``' ``RequiresQuota`` test routes."""
    from quota_helpers import install_quota_routes

    return install_quota_routes(app)


@pytest.fixture
def runs(quota_app) -> list[int]:
    """One entry per run of a counting test handler."""
    return quota_app.state.quota_runs


@pytest.fixture
async def owner(quota_app, user_client):
    """A tenant owner's client whose plan allows 2 of the test meter."""
    from api_helpers import create_tenant
    from quota_helpers import limit_plan

    async with user_client("owner@x.io") as (client, _):
        tenant = await create_tenant(client)
        await limit_plan(quota_app, tenant["id"], 2)
        client.tenant_id = tenant["id"]
        yield client
