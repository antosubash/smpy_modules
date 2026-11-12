"""The worker-side subject helpers are importable from the contracts package (#274)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sm_billing.contracts import current_subject_mode, subject_for_tenant, subject_for_user
from sm_billing.core import subjects


def test_exports_are_the_subjects_helpers() -> None:
    assert subject_for_user is subjects.subject_for_user
    assert subject_for_tenant is subjects.subject_for_tenant
    assert current_subject_mode is subjects.subject_mode


def test_helpers_build_the_keys_billing_uses() -> None:
    user_id = uuid.uuid4()
    assert subject_for_user(user_id) == f"user:{user_id}"
    assert subject_for_tenant("acme") == "acme"


def test_current_subject_mode_defaults_to_tenant() -> None:
    app = SimpleNamespace(state=SimpleNamespace())
    assert current_subject_mode(app) == "tenant"


def test_requires_quota_is_the_metering_dependency() -> None:
    """ai's ``RequiresAiRequest`` reaches it through contracts (#336)."""
    from sm_billing.contracts import RequiresQuota, __all__

    assert "RequiresQuota" in __all__
    dep = RequiresQuota("ai.requests", 2)
    assert dep.dependency.__qualname__ == "RequiresQuota.<locals>.requires_quota"
    custom = RequiresQuota("ai.requests", key_header="X-Op")
    assert custom.dependency.__module__ == "sm_billing.metering.deps"
    with pytest.raises(ValueError, match="qty must be"):
        RequiresQuota("ai.requests", 0)
