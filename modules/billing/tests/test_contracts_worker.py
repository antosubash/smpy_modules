"""The contracts deliver what workers and entitlement callers need (#274)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sm_billing import constants as c
from sm_billing import contracts
from sm_billing.errors import BillingError
from sm_billing.settings import BillingSettings


def test_subject_for_user_normalises_its_input() -> None:
    user_id = uuid.uuid4()
    canonical = f"user:{user_id}"
    assert contracts.subject_for_user(user_id.hex) == canonical
    assert contracts.subject_for_user(str(user_id).upper()) == canonical
    assert contracts.subject_for_user(str(user_id)) == canonical


def test_subject_for_user_rejects_a_non_uuid() -> None:
    with pytest.raises(ValueError):
        contracts.subject_for_user("not-a-uuid")


def test_worker_subject_mode_reads_the_db_backed_setting(monkeypatch) -> None:
    import background_tasks

    seen: list[tuple[type, str]] = []

    def fake_settings_for(cls, package, **_kw):
        seen.append((cls, package))
        return BillingSettings(subject_mode="user")

    monkeypatch.setattr(background_tasks, "settings_for", fake_settings_for)
    assert contracts.worker_subject_mode() == "user"
    assert seen == [(BillingSettings, c.PACKAGE)]


def test_subject_for_request_bills_the_user_in_user_mode() -> None:
    user_id = uuid.uuid4()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(**{c.SUBJECTS_STATE_ATTR: "user"})),
        state=SimpleNamespace(user=SimpleNamespace(id=user_id), tenant_id="acme"),
    )
    assert contracts.subject_for_request(request) == f"user:{user_id}"


def test_subject_for_request_needs_a_user_in_user_mode() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(**{c.SUBJECTS_STATE_ATTR: "user"})),
        state=SimpleNamespace(user=None, tenant_id=None),
    )
    with pytest.raises(BillingError) as err:
        contracts.subject_for_request(request)
    assert err.value.status_code == 401


def test_subject_for_request_bills_the_tenant_in_tenant_mode(app) -> None:
    request = SimpleNamespace(app=app, state=SimpleNamespace(user=None, tenant_id="acme"))
    assert contracts.subject_for_request(request) == "acme"
