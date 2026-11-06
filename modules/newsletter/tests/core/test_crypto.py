"""The SMTP password's Fernet layer."""

from __future__ import annotations

import logging

import pytest
from sm_newsletter.core import crypto
from sm_newsletter.core.errors import SmtpPasswordUnreadable
from sm_newsletter.core.settings import NewsletterSettings


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", "secret-a")
    monkeypatch.setattr(crypto, "_secret_provider", None)
    crypto._warned_plaintext.clear()


def test_round_trip():
    stored = crypto.encrypt_value("pw")
    assert stored.startswith("enc:v1:")
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
