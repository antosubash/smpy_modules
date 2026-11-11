"""Fernet layer for the stored Stripe secrets."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from hashlib import sha256

import pytest
from cryptography.fernet import Fernet
from sm_billing.core import crypto


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.delenv("SM_SECRET_KEY_PREVIOUS", raising=False)
    crypto._dotenv_previous.cache_clear()
    crypto.set_secret_provider(lambda: "test-secret")
    crypto._warned_plaintext.clear()
    crypto._warned_v1.clear()
    yield
    crypto.set_secret_provider(lambda: "")
    crypto._dotenv_previous.cache_clear()


def _v1(plain: str, secret: str = "test-secret") -> str:
    key = urlsafe_b64encode(sha256(secret.encode()).digest())
    return "enc:v1:" + Fernet(key).encrypt(plain.encode()).decode()


def test_round_trip():
    stored = crypto.encrypt_value("sk_test_123")
    assert stored.startswith(crypto.ENC_V2)
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


def test_v1_still_decrypts_and_warns_once(caplog):
    with caplog.at_level("WARNING"):
        assert crypto.decrypt_value(_v1("sk_old"), "stripe_secret_key") == "sk_old"
        crypto.decrypt_value(_v1("sk_old"), "stripe_secret_key")
    assert sum("v1 format" in r.message for r in caplog.records) == 1


def test_unknown_version_is_unreadable():
    with pytest.raises(crypto.BillingKeyUnreadableError):
        crypto.decrypt_value("enc:v9:x", "stripe_secret_key")


def test_previous_secret_opens_old_values(monkeypatch):
    v2 = crypto.encrypt_value("sk_v2")
    v1 = _v1("sk_v1")
    crypto.set_secret_provider(lambda: "rotated-secret")
    with pytest.raises(crypto.BillingKeyUnreadableError) as exc:
        crypto.decrypt_value(v2, "stripe_secret_key")
    assert "SM_SECRET_KEY_PREVIOUS" in str(exc.value)
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", '["test-secret"]')
    assert crypto.decrypt_value(v2, "stripe_secret_key") == "sk_v2"
    assert crypto.decrypt_value(v1, "stripe_secret_key") == "sk_v1"
    rotated = crypto.reencrypt_value(v2, "stripe_secret_key")
    assert crypto.reencrypt_value(rotated, "stripe_secret_key") is None


def test_reencrypt_seals_plaintext():
    sealed = crypto.reencrypt_value("sk_plain", "stripe_secret_key")
    assert sealed.startswith(crypto.ENC_V2)
    assert crypto.decrypt_value(sealed, "stripe_secret_key") == "sk_plain"
    assert crypto.reencrypt_value("", "stripe_secret_key") is None
