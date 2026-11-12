"""Fernet layer: roundtrip, the stored-value states, rotation, missing secret."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from hashlib import sha256

import pytest
from cryptography.fernet import Fernet
from sm_ai.contracts.errors import AiKeyUnreadableError
from sm_ai.core import crypto

SECRET = "test-secret-key-for-crypto"


@pytest.fixture(autouse=True)
def _secret_env(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    monkeypatch.delenv("SM_SECRET_KEY_PREVIOUS", raising=False)
    crypto._dotenv_previous.cache_clear()
    crypto._warned_plaintext.clear()
    crypto._warned_v1.clear()
    yield
    crypto._dotenv_previous.cache_clear()


def _v1(plain: str, secret: str = SECRET) -> str:
    """A value stored the 0.0.15 way."""
    key = urlsafe_b64encode(sha256(secret.encode()).digest())
    return "enc:v1:" + Fernet(key).encrypt(plain.encode()).decode()


class TestEncrypt:
    def test_roundtrip(self):
        stored = crypto.encrypt_value("sk-ant-abc123")
        assert stored.startswith(crypto.ENC_V2)
        assert crypto.decrypt_value(stored, "chat_api_key") == "sk-ant-abc123"

    def test_each_encryption_differs(self):
        # Fernet includes a random IV — equality would mean something is wrong.
        assert crypto.encrypt_value("x") != crypto.encrypt_value("x")

    def test_missing_secret_key_raises(self, monkeypatch):
        # conftest moved cwd to an empty tmp dir, so no .env can supply it.
        monkeypatch.delenv("SM_SECRET_KEY", raising=False)
        with pytest.raises(RuntimeError, match="SM_SECRET_KEY"):
            crypto.encrypt_value("x")


class TestDecrypt:
    def test_empty_string_passes_through(self):
        assert crypto.decrypt_value("", "chat_api_key") == ""

    def test_wrong_secret_raises_unreadable(self, monkeypatch):
        stored = crypto.encrypt_value("sk-123")
        # The secret is re-resolved per call, so the rotation applies to the
        # very next decrypt — no restart needed.
        monkeypatch.setenv("SM_SECRET_KEY", "a-different-secret")
        with pytest.raises(AiKeyUnreadableError) as exc:
            crypto.decrypt_value(stored, "chat_api_key")
        assert exc.value.field == "chat_api_key"

    def test_garbage_after_prefix_raises_unreadable(self):
        with pytest.raises(AiKeyUnreadableError):
            crypto.decrypt_value(crypto.ENC_V2 + "not-a-token", "chat_api_key")

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


class TestFormats:
    def test_v1_still_decrypts_and_warns_once(self, caplog):
        with caplog.at_level("WARNING"):
            assert crypto.decrypt_value(_v1("sk-old"), "chat_api_key") == "sk-old"
            assert crypto.decrypt_value(_v1("sk-old"), "chat_api_key") == "sk-old"
        assert sum("v1 format" in r.message for r in caplog.records) == 1

    def test_an_unknown_version_is_unreadable_never_plaintext(self):
        with pytest.raises(AiKeyUnreadableError):
            crypto.decrypt_value("enc:v9:whatever", "chat_api_key")


class TestRotation:
    def test_previous_key_opens_v2_and_v1(self, monkeypatch):
        v2 = crypto.encrypt_value("sk-v2")
        v1 = _v1("sk-v1")
        monkeypatch.setenv("SM_SECRET_KEY", "the-new-secret")
        with pytest.raises(AiKeyUnreadableError) as exc:
            crypto.decrypt_value(v2, "chat_api_key")
        assert "SM_SECRET_KEY_PREVIOUS" in str(exc.value)
        assert SECRET not in str(exc.value)
        monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", SECRET)
        assert crypto.decrypt_value(v2, "chat_api_key") == "sk-v2"
        assert crypto.decrypt_value(v1, "chat_api_key") == "sk-v1"

    def test_previous_is_one_key_or_a_json_list(self, monkeypatch):
        monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", " old-1 ")
        assert crypto.previous_secrets() == (" old-1 ",), "verbatim, like SM_SECRET_KEY"
        monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", '["old-1", " ", " old-2"]')
        assert crypto.previous_secrets() == ("old-1", " old-2")
        monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", "  ")
        assert crypto.previous_secrets() == ()

    def test_invalid_json_names_the_variable_never_the_value(self, monkeypatch):
        monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", '["leaky-old-key"')
        with pytest.raises(RuntimeError) as exc:
            crypto.previous_secrets()
        assert "SM_SECRET_KEY_PREVIOUS" in str(exc.value)
        assert "leaky-old-key" not in str(exc.value)
        assert exc.value.__cause__ is None

    def test_previous_comes_from_the_project_env_file(self, monkeypatch, tmp_path):
        old = crypto.encrypt_value("sk-1")
        (tmp_path / ".env.example").write_text("")
        (tmp_path / ".env").write_text(f"SM_SECRET_KEY_PREVIOUS={SECRET}\n")
        monkeypatch.setenv("SM_PROJECT_ROOT", str(tmp_path))
        monkeypatch.setenv("SM_SECRET_KEY", "the-new-secret")
        crypto._dotenv_previous.cache_clear()
        assert crypto.decrypt_value(old, "chat_api_key") == "sk-1"

    def test_reencrypt(self, monkeypatch):
        current = crypto.encrypt_value("sk-now")
        assert crypto.reencrypt_value("", "chat_api_key") is None
        assert crypto.reencrypt_value(current, "chat_api_key") is None
        sealed = crypto.reencrypt_value("sk-plain", "chat_api_key")
        assert sealed.startswith(crypto.ENC_V2)
        assert crypto.decrypt_value(sealed, "chat_api_key") == "sk-plain"
        upgraded = crypto.reencrypt_value(_v1("sk-v1"), "chat_api_key")
        assert crypto.decrypt_value(upgraded, "chat_api_key") == "sk-v1"
        monkeypatch.setenv("SM_SECRET_KEY", "the-new-secret")
        monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", SECRET)
        rotated = crypto.reencrypt_value(current, "chat_api_key")
        monkeypatch.delenv("SM_SECRET_KEY_PREVIOUS")
        assert crypto.decrypt_value(rotated, "chat_api_key") == "sk-now"
        with pytest.raises(AiKeyUnreadableError):
            crypto.reencrypt_value(current, "chat_api_key")


class TestDotenvFallback:
    """The ``.env`` the secret comes from is the project's, never the cwd's (#124)."""

    @pytest.fixture(autouse=True)
    def _no_env_secret(self, monkeypatch):
        monkeypatch.delenv("SM_SECRET_KEY", raising=False)
        crypto._dotenv_secret.cache_clear()
        yield
        crypto._dotenv_secret.cache_clear()

    def _project(self, root, secret: str):
        root.mkdir(parents=True)
        (root / ".env.example").write_text("")  # marks the project root
        (root / ".env").write_text(f"SM_SECRET_KEY={secret}\n")
        return root

    def test_sm_project_root_anchors_the_file_whatever_the_cwd(self, monkeypatch, tmp_path):
        project = self._project(tmp_path / "project", "project-secret")
        elsewhere = self._project(tmp_path / "elsewhere", "some-other-secret")
        monkeypatch.chdir(elsewhere)
        monkeypatch.setenv("SM_PROJECT_ROOT", str(project))

        stored = crypto.encrypt_value("sk-1")

        crypto.set_secret_provider(lambda: "project-secret")
        assert crypto.decrypt_value(stored, "chat_api_key") == "sk-1"

    def test_a_subdirectory_finds_the_project_root_file(self, monkeypatch, tmp_path):
        # e.g. a worker or CLI started from host/ or modules/ai/.
        project = self._project(tmp_path / "project", "root-secret")
        (project / "host").mkdir()
        monkeypatch.chdir(project / "host")

        stored = crypto.encrypt_value("sk-2")

        crypto.set_secret_provider(lambda: "root-secret")
        assert crypto.decrypt_value(stored, "chat_api_key") == "sk-2"

    def test_the_placeholder_default_is_never_used(self, monkeypatch, tmp_path):
        # BootstrapSettings defaults secret_key to a placeholder; encrypting
        # under it would make every key unreadable once a real one is set.
        project = tmp_path / "project"
        project.mkdir()
        (project / ".env.example").write_text("")
        monkeypatch.setenv("SM_PROJECT_ROOT", str(project))
        with pytest.raises(RuntimeError, match="SM_SECRET_KEY"):
            crypto.encrypt_value("x")
