"""The SMTP password's Fernet layer."""

from __future__ import annotations

import logging
from base64 import urlsafe_b64encode
from hashlib import sha256

import pytest
from cryptography.fernet import Fernet
from sm_newsletter.core import crypto
from sm_newsletter.core.errors import SmtpPasswordUnreadable
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.sending.runtime import PlaintextPassword, refuse_plaintext_password


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", "secret-a")
    monkeypatch.delenv("SM_SECRET_KEY_PREVIOUS", raising=False)
    monkeypatch.setattr(crypto, "_secret_provider", None)
    crypto._dotenv_previous.cache_clear()
    crypto._warned_plaintext.clear()
    crypto._warned_v1.clear()
    yield
    crypto._dotenv_previous.cache_clear()


def _v1(plain: str, secret: str = "secret-a") -> str:
    key = urlsafe_b64encode(sha256(secret.encode()).digest())
    return "enc:v1:" + Fernet(key).encrypt(plain.encode()).decode()


def test_round_trip():
    stored = crypto.encrypt_value("pw")
    assert stored.startswith("enc:v2:")
    assert crypto.decrypt_value(stored, "smtp_password") == "pw"


def test_plaintext_tolerated_and_warned_once(caplog):
    with caplog.at_level(logging.WARNING, logger=crypto.logger.name):
        assert crypto.decrypt_value("pw", "smtp_password") == "pw"
        assert crypto.decrypt_value("pw", "smtp_password") == "pw"
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_other_secret_is_unreadable(monkeypatch):
    stored = crypto.encrypt_value("pw")
    monkeypatch.setenv("SM_SECRET_KEY", "secret-b")
    with pytest.raises(SmtpPasswordUnreadable):
        crypto.decrypt_value(stored, "smtp_password")


def test_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("SM_SECRET_KEY")
    monkeypatch.setattr(crypto, "_dotenv_secret", lambda: "")
    with pytest.raises(RuntimeError, match="SM_SECRET_KEY"):
        crypto.encrypt_value("pw")


def test_smtp_password_helper_decrypts():
    settings = NewsletterSettings(smtp_password=crypto.encrypt_value("pw"))
    assert crypto.smtp_password(settings) == "pw"
    assert crypto.smtp_password(NewsletterSettings()) == ""


def test_v1_still_decrypts_and_warns_once(caplog):
    with caplog.at_level(logging.WARNING, logger=crypto.logger.name):
        assert crypto.decrypt_value(_v1("pw"), "smtp_password") == "pw"
        assert crypto.decrypt_value(_v1("pw"), "smtp_password") == "pw"
    assert sum("v1 format" in r.getMessage() for r in caplog.records) == 1


def test_unknown_version_is_unreadable():
    with pytest.raises(SmtpPasswordUnreadable):
        crypto.decrypt_value("enc:v9:x", "smtp_password")


def test_previous_secret_opens_old_values(monkeypatch):
    v2 = crypto.encrypt_value("pw2")
    v1 = _v1("pw1")
    monkeypatch.setenv("SM_SECRET_KEY", "secret-b")
    with pytest.raises(SmtpPasswordUnreadable):
        crypto.decrypt_value(v2, "smtp_password")
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", "secret-a")
    assert crypto.decrypt_value(v2, "smtp_password") == "pw2"
    assert crypto.decrypt_value(v1, "smtp_password") == "pw1"
    rotated = crypto.reencrypt_value(v1, "smtp_password")
    monkeypatch.delenv("SM_SECRET_KEY_PREVIOUS")
    assert crypto.decrypt_value(rotated, "smtp_password") == "pw1"


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_workers_accept_either_encrypted_format(version):
    stored = _v1("pw") if version == "v1" else crypto.encrypt_value("pw")
    refuse_plaintext_password(NewsletterSettings(transport="smtp", smtp_password=stored))


def test_workers_refuse_plaintext():
    with pytest.raises(PlaintextPassword):
        refuse_plaintext_password(NewsletterSettings(transport="smtp", smtp_password="pw"))
