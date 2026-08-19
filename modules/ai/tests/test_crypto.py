"""Fernet layer: roundtrip, the three stored-value states, missing secret."""

from __future__ import annotations

import pytest
from sm_ai import crypto
from sm_ai.contracts.errors import AiKeyUnreadableError

SECRET = "test-secret-key-for-crypto"


@pytest.fixture(autouse=True)
def _secret_env(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    crypto._warned_plaintext.clear()


class TestEncrypt:
    def test_roundtrip(self):
        stored = crypto.encrypt_value("sk-ant-abc123")
        assert stored.startswith(crypto.ENC_PREFIX)
        assert crypto.decrypt_value(stored, "chat_api_key") == "sk-ant-abc123"

    def test_each_encryption_differs(self):
        # Fernet includes a random IV — equality would mean something is wrong.
        assert crypto.encrypt_value("x") != crypto.encrypt_value("x")

    def test_missing_secret_key_raises(self, monkeypatch):
        # conftest moved cwd to an empty tmp dir, so no .env can supply it.
        monkeypatch.delenv("SM_SECRET_KEY", raising=False)
        crypto._fernet.cache_clear()
        with pytest.raises(RuntimeError, match="SM_SECRET_KEY"):
            crypto.encrypt_value("x")


class TestDecrypt:
    def test_empty_string_passes_through(self):
        assert crypto.decrypt_value("", "chat_api_key") == ""

    def test_wrong_secret_raises_unreadable(self, monkeypatch):
        stored = crypto.encrypt_value("sk-123")
        monkeypatch.setenv("SM_SECRET_KEY", "a-different-secret")
        # The Fernet is process-cached; a rotated secret takes effect on
        # restart. Simulate the restarted process.
        crypto._fernet.cache_clear()
        with pytest.raises(AiKeyUnreadableError) as exc:
            crypto.decrypt_value(stored, "chat_api_key")
        assert exc.value.field == "chat_api_key"

    def test_garbage_after_prefix_raises_unreadable(self):
        with pytest.raises(AiKeyUnreadableError):
            crypto.decrypt_value(crypto.ENC_PREFIX + "not-a-token", "chat_api_key")

    def test_plaintext_passes_through_with_warning(self, caplog):
        # A key pasted through the generic settings UI or seeded via env.
        with caplog.at_level("WARNING"):
            assert crypto.decrypt_value("sk-plain", "chat_api_key") == "sk-plain"
        assert any("unencrypted" in r.message for r in caplog.records)

    def test_plaintext_warns_only_once_per_field(self, caplog):
        with caplog.at_level("WARNING"):
            crypto.decrypt_value("sk-plain", "chat_api_key")
            crypto.decrypt_value("sk-plain", "chat_api_key")
        assert sum("unencrypted" in r.message for r in caplog.records) == 1
