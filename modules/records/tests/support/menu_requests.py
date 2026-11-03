"""Shared record test builders."""

from __future__ import annotations
from types import SimpleNamespace
from typing import Any
import pytest
from fastapi import FastAPI
from simple_module_core.menu import MenuRegistry, MenuSection
from sm_records.core import constants
from sm_records.web import menu
from sm_records.web.menu import MenuType
from sm_records.module import RecordsModule
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import TenancyMode, tenant_scope
from starlette.requests import Request
from tests.support.app_harness import seed_type

def _user(*roles: str) -> SimpleNamespace:
    return SimpleNamespace(id="u", roles=list(roles))


def _request(
    path: str = "/admin/records/",
    *,
    user: Any = None,
    held: set[str] | None = None,
    tenant: str | None = None,
    mode: TenancyMode = TenancyMode.SINGLE,
) -> Request:
    app = FastAPI()
    setattr(app.state, constants.PACKAGE, SimpleNamespace(tenancy=mode))
    state = {"user": user, "tenant_id": tenant, "resolved_permissions": held or set()}
    return Request({"type": "http", "path": path, "app": app, "state": state, "headers": []})
