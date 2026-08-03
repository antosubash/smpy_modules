"""Smoke tests: the demo host boots and mounts its modules.

These catch wiring breaks (missing dependency, entry point typo, route
prefix collision) that module-level tests can't see because they build a
minimal app instead of the real host.
"""

from __future__ import annotations

import pytest
from simple_module_hosting import Settings, create_app


@pytest.fixture
def app():
    return create_app(Settings())


def test_app_boots(app):
    assert app is not None


def _module_names(app) -> set[str]:
    """Booted modules live on the framework's Services container."""
    return {m.meta.name for m in app.state.sm.modules}


def test_core_modules_registered(app):
    assert {"Auth", "Users", "Dashboard", "Permissions"} <= _module_names(app)


def test_openapi_schema_generates(app):
    schema = app.openapi()
    assert schema["openapi"].startswith("3.")
