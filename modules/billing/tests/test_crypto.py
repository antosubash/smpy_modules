"""Fernet layer for the stored Stripe secrets."""

from __future__ import annotations

import pytest
from sm_billing import crypto


@pytest.fixture(autouse=True)
def _secret():
    crypto.set_secret_provider(lambda: "test-secret")
    crypto._warned_plaintext.clear()
    yield
    crypto.set_secret_provider(lambda: "")


def test_round_trip():
    stored = crypto.encrypt_value("sk_test_123")
    assert stored.startswith(crypto.ENC_PREFIX)
    assert "sk_test_123" not in stored
    assert crypto.decrypt_value(stored, "stripe_secret_key") == "sk_test_123"


def test_each_encryption_differs():
    assert crypto.encrypt_value("x") != crypto.encrypt_value("x")


def test_empty_passes_through():
    assert crypto.decrypt_value("", "stripe_secret_key") == ""


def test_rotated_secret_is_unreadable():
    stored = crypto.encrypt_value("sk_test_123")
    crypto.set_secret_provider(lambda: "another-secret")
    with pytest.raises(crypto.BillingKeyUnreadableError) as exc:
        crypto.decrypt_value(stored, "stripe_secret_key")
    assert exc.value.field == "stripe_secret_key"


def test_plaintext_passes_through_and_warns_once(caplog):
    with caplog.at_level("WARNING"):
        assert crypto.decrypt_value("sk_plain", "stripe_secret_key") == "sk_plain"
        crypto.decrypt_value("sk_plain", "stripe_secret_key")
    assert sum("unencrypted" in r.message for r in caplog.records) == 1


def test_no_secret_refuses_to_encrypt():
    crypto.set_secret_provider(lambda: "")
    with pytest.raises(RuntimeError, match="secret_key"):
        crypto.encrypt_value("x")
