from __future__ import annotations

from simple_module_core.permissions import PermissionRegistry, grants
from sm_billing import constants as c
from sm_billing.module import BillingModule
from sm_billing.settings import BillingSettings


def test_settings_ignore_environment(monkeypatch):
    monkeypatch.setenv("SM_BILLING_PROVIDER", "stripe")
    monkeypatch.setenv("PROVIDER", "stripe")
    assert BillingSettings().provider == c.PROVIDER_MANUAL


def test_provider_requires_restart():
    extra = BillingSettings.model_fields["provider"].json_schema_extra
    assert extra["requires_restart"] is True


def _role_perms(role: str) -> set[str]:
    registry = PermissionRegistry()
    BillingModule().register_permissions(registry)
    return set(registry.get_permissions_for_roles([role], registry.role_map))


def test_owner_can_view_and_manage():
    perms = _role_perms(c.ROLE_TENANT_OWNER)
    assert grants(perms, c.PERM_VIEW)
    assert grants(perms, c.PERM_MANAGE)


def test_tenant_admin_can_only_view():
    perms = _role_perms(c.ROLE_TENANT_ADMIN)
    assert grants(perms, c.PERM_VIEW)
    assert not grants(perms, c.PERM_MANAGE)


def test_member_gets_nothing():
    assert not grants(_role_perms("tenant:member"), c.PERM_VIEW)


async def test_module_boots_with_state(app):
    services = getattr(app.state, c.PACKAGE)
    assert isinstance(services.settings, BillingSettings)
