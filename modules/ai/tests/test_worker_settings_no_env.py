"""The worker path reads no ``SM_AI_*`` env and no cwd-relative ``.env`` (#124).

The web host never did the first since ``AiSettings`` became DB-only, and a
worker must agree with it: a Celery worker started from another directory
used to see a different provider or secret, surfacing as
``AiKeyUnreadableError`` or a call to the wrong endpoint.
"""

from __future__ import annotations

import pytest
from ai_worker_support import DB_SECRET, key_of, put, run_task
from sm_ai import crypto, services
from sm_ai.contracts.errors import AiNotConfiguredError

pytestmark = pytest.mark.usefixtures("worker_env")


class TestNoDbRows:
    """Without a row a field is the default — never an ``SM_AI_*`` variable."""

    def test_migrated_but_empty_table(self, db, monkeypatch):
        monkeypatch.setenv("SM_SECRET_KEY", "env-secret")

        assert run_task(services.current_settings).chat_model == "claude-opus-5"
        with pytest.raises(AiNotConfiguredError) as exc:
            run_task()
        assert exc.value.field == "chat_api_key"  # SM_AI_CHAT_API_KEY is dead

    def test_unreachable_database_falls_back_to_defaults(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setenv("SM_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/no/such/dir.db")

        assert run_task(services.current_settings).chat_model == "claude-opus-5"
        assert "database read failed" in caplog.text

    def test_the_fallback_warning_never_carries_the_database_url(self, monkeypatch, caplog):
        # A refused connection: drivers put host, user — sometimes the whole
        # URL — in the message and the traceback. None of it may reach a log.
        url = "postgresql+asyncpg://admin:hunter2-secret@127.0.0.1:1/ai"
        monkeypatch.setenv("SM_DATABASE_URL", url)

        run_task(services.current_settings)

        assert "database read failed" in caplog.text
        assert "hunter2-secret" not in caplog.text
        assert "admin" not in caplog.text
        assert all(record.exc_info is None for record in caplog.records)


class TestSecretFromAnotherDirectory:
    def test_sm_project_root_supplies_the_env_secret_whatever_the_cwd(
        self, db, monkeypatch, tmp_path
    ):
        # A worker started outside the repo root (#124): the project's .env
        # is found through SM_PROJECT_ROOT, not resolved against the cwd.
        project = tmp_path / "project"
        project.mkdir()
        (project / ".env").write_text("SM_SECRET_KEY=project-env-secret\n")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / ".env").write_text("SM_SECRET_KEY=wrong-secret\n")
        monkeypatch.chdir(elsewhere)
        monkeypatch.setenv("SM_PROJECT_ROOT", str(project))

        crypto.set_secret_provider(lambda: "project-env-secret")
        stored = crypto.encrypt_value("sk-project")
        crypto._secret_provider = None
        put(db, "host.secret_key", DB_SECRET)
        put(db, "sm_ai.chat_api_key", stored)

        assert key_of(run_task()) == "sk-project"
