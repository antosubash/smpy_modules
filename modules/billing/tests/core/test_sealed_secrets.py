"""Billing secrets seal on dump without changing held or hydrated values."""

from __future__ import annotations

import gc
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from simple_module_core.settings_hydrate import build_settings
from sm_billing.core import crypto
from sm_billing.core.settings import BillingSettings
from sm_billing.module import BillingModule

FIELDS = ("stripe_secret_key", "stripe_webhook_secret")
PLAIN = "legacy-stripe-secret"


@pytest.fixture(autouse=True)
def isolated_provider(monkeypatch):
    monkeypatch.setattr(crypto, "_secret_provider", None)
    monkeypatch.setattr(crypto, "_attached", None, raising=False)


def attached_app(secret="test-secret"):
    app = FastAPI()
    BillingModule().register_settings(app)
    app.state.sm = SimpleNamespace(settings=SimpleNamespace(secret_key=secret))
    return app


@pytest.mark.parametrize("field", FIELDS)
def test_headless_registration_seals_dumps_without_mutating_the_value(field):
    app = attached_app()  # no lifespan: the same registration as set_setting.py
    settings = BillingSettings(**{field: PLAIN})
    for _ in range(2):
        stored = settings.model_dump()[field]
        assert stored.startswith("enc:v2:") and PLAIN not in stored
        assert crypto.decrypt_value(stored, field) == PLAIN
        assert json.loads(settings.model_dump_json())[field].startswith("enc:v2:")
        assert getattr(settings, field) == PLAIN
    assert app.state.sm.settings.secret_key == "test-secret"


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", [None, "", "   ", "enc:v2:opaque", "enc:v9:opaque"])
def test_clear_and_ciphertext_pass_through_without_a_key(field, value):
    app = attached_app(secret="")
    settings = BillingSettings(**{field: value})
    assert settings.model_dump()[field] == (value.strip() if value else "")
    if value is None:
        assert getattr(settings, field) == ""
    assert app.state.sm.settings.secret_key == ""


@pytest.mark.parametrize("field", FIELDS)
def test_a_live_app_without_a_key_refuses_to_dump_plaintext(field):
    app = attached_app(secret="")
    with pytest.raises(Exception, match="secret_key"):
        BillingSettings(**{field: PLAIN}).model_dump()
    assert app.state.sm.settings.secret_key == ""


@pytest.mark.parametrize("dead_app", [False, True])
def test_hydration_without_a_live_app_keeps_legacy_plaintext(dead_app):
    if dead_app:
        app = attached_app()
        del app
        gc.collect()
    settings = build_settings(BillingSettings, {FIELDS[0]: (PLAIN, "string")}, lenient=True)
    assert settings.model_dump()[FIELDS[0]] == PLAIN
    assert getattr(settings.model_copy(deep=True), FIELDS[0]) == PLAIN
    settings.model_dump_json()


def test_a_script_provider_supersedes_a_dead_app_provider():
    app = attached_app()
    del app
    gc.collect()
    crypto.set_secret_provider(lambda: "script-secret")
    stored = BillingSettings(stripe_secret_key=PLAIN).model_dump()[FIELDS[0]]
    assert stored.startswith("enc:v2:")
    assert crypto.decrypt_value(stored, FIELDS[0]) == PLAIN
