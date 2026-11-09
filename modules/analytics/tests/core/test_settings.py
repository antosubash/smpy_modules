from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from simple_module_core.tenancy import TenancyMode
from simple_module_db import tenant_context
from sm_analytics.core.settings import AnalyticsSettings
from sm_analytics.core.tenancy import resolved
from starlette.requests import Request


def test_settings_ignore_environment(monkeypatch):
    monkeypatch.setenv("RETENTION_DAYS", "1")
    monkeypatch.setenv("SM_ANALYTICS_RETENTION_DAYS", "2")
    monkeypatch.setenv("GEO_DATABASE_PATH", "/untrusted.mmdb")
    settings = AnalyticsSettings()
    assert settings.retention_days == 90 and settings.geo_database_path == ""


def test_upstream_tenant_wins_even_on_single_tenant_child():
    app = SimpleNamespace(state=SimpleNamespace(sm=SimpleNamespace(tenancy=TenancyMode.SINGLE)))
    request = Request({"type": "http", "app": app, "state": {"tenant_id": "upstream"}})
    assert resolved(request, 403) == "upstream"
    request = Request({"type": "http", "app": app, "state": {}})
    with tenant_context("parent"):
        assert resolved(request, 403) == "parent"
    assert resolved(request, 403) == "default"
    app.state.sm.tenancy = TenancyMode.MULTI
    for code in (403, 404):
        with pytest.raises(HTTPException) as err:
            resolved(request, code)
        assert err.value.status_code == code
