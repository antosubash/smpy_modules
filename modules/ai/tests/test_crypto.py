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
