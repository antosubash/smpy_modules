"""``resolve_model()`` outside the web host — a Celery worker's view (#100).

Nothing here builds an app or registers the module: that is the whole point.
A worker imports consumer code and calls ``sm_ai.contracts`` with an empty
holder, so settings must come from the shared settings table (and the secret
the web app encrypted keys under). ``SM_AI_*`` env is ignored, as on the web
host (#124): with no row, a field is the pydantic default — see
``test_worker_settings_no_env``.

Celery itself is not a test dependency and framework 0.0.35 ships no
``background_tasks`` package, so the "task" is a plain function run on a
fresh thread — both ways a task body commonly reaches the contract (sync, and
inside its own ``asyncio.run``) are covered.
"""

from __future__ import annotations

import asyncio

import pytest
from ai_worker_support import DB_SECRET, encrypt_as_web_host, key_of, put, run_task
from pydantic_ai.models.anthropic import AnthropicModel
from settings.models import Setting
from sm_ai import constants, crypto, services, worker_settings
from sm_ai.contracts import resolve_model
from sm_ai.settings import AiSettings
from sqlmodel import create_engine

pytestmark = pytest.mark.usefixtures("worker_env")


class TestDbStoredSettings:
    def test_resolves_with_db_values_and_the_hosts_stored_secret(self, db):
        put(db, "host.secret_key", DB_SECRET)
        put(db, "sm_ai.chat_model", "from-db")
        put(db, "sm_ai.chat_api_key", encrypt_as_web_host("sk-db"))

        model = run_task()

        assert isinstance(model, AnthropicModel)
        assert model.model_name == "from-db"
        assert key_of(model) == "sk-db"

    def test_typed_rows_are_parsed(self, db):
        put(db, "sm_ai.embedding_dim", "1536", "int")
        assert services.current_settings().embedding_dim == 1536

    def test_explicit_env_secret_beats_the_stored_one(self, db, monkeypatch):
        monkeypatch.setenv("SM_SECRET_KEY", "explicit-env-secret")
        put(db, "host.secret_key", DB_SECRET)
        crypto.set_secret_provider(lambda: "explicit-env-secret")
        stored = crypto.encrypt_value("sk-env-secret")
        crypto._secret_provider = None
        put(db, "sm_ai.chat_api_key", stored)

        assert key_of(run_task()) == "sk-env-secret"

    def test_inside_a_running_event_loop(self, keyed_db):
        db = keyed_db
        # Tasks that drive an agent call asyncio.run(...) and resolve inside
        # it; the hydration read must not try to nest a loop.
        put(db, "sm_ai.chat_model", "from-db")

        async def body():
            return resolve_model()

        assert asyncio.run(body()).model_name == "from-db"


class TestCache:
    def test_cached_until_invalidated(self, keyed_db):
        db = keyed_db
        put(db, "sm_ai.chat_model", "first")
        assert resolve_model().model_name == "first"

        put(db, "sm_ai.chat_model", "second")
        assert resolve_model().model_name == "first"  # per-process cache

        services.invalidate()
        assert resolve_model().model_name == "second"

    def test_ttl_expiry_rereads(self, keyed_db, monkeypatch):
        db = keyed_db
        # The only cross-process path a console save has to a worker.
        monkeypatch.setattr(constants, "LAZY_SETTINGS_TTL_SECONDS", 0.0)
        put(db, "sm_ai.chat_model", "first")
        assert resolve_model().model_name == "first"

        put(db, "sm_ai.chat_model", "second")
        assert resolve_model().model_name == "second"

    def test_one_read_per_ttl(self, keyed_db, monkeypatch):
        calls = []
        real = worker_settings._hydrate
        monkeypatch.setattr(worker_settings, "_hydrate", lambda: calls.append(1) or real())
        for _ in range(5):
            resolve_model()
        assert len(calls) == 1


class TestResilience:
    """A worker outlives database blips; none may pin it to the wrong settings."""

    def test_a_fallback_is_retried_soon_not_kept_for_the_ttl(self, monkeypatch, tmp_path):
        path = tmp_path / "later.db"
        monkeypatch.setenv("SM_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
        monkeypatch.setattr(constants, "LAZY_SETTINGS_RETRY_SECONDS", 0.0)
        assert services.current_settings().chat_model == "claude-opus-5"  # no database yet

        engine = create_engine(f"sqlite:///{path}")
        Setting.__table__.create(engine)
        put(engine, "sm_ai.chat_model", "from-db")
        engine.dispose()
        assert services.current_settings().chat_model == "from-db"  # the 60s TTL did not apply

    def test_a_missing_sqlite_file_is_not_created(self, monkeypatch, tmp_path):
        path = tmp_path / "never.db"
        monkeypatch.setenv("SM_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
        services.current_settings()
        assert not path.exists()

    def test_the_warning_is_logged_once_per_outage(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setenv("SM_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/gone.db")
        monkeypatch.setattr(constants, "LAZY_SETTINGS_RETRY_SECONDS", 0.0)
        for _ in range(3):
            services.current_settings()
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1

    def test_a_hung_read_is_bounded(self, db, monkeypatch):
        async def hang(_url):
            await asyncio.sleep(30)

        monkeypatch.setattr(worker_settings, "_read", hang)
        monkeypatch.setattr(constants, "LAZY_SETTINGS_READ_TIMEOUT_SECONDS", 0.1)
        assert run_task(services.current_settings).chat_model == "claude-opus-5"

    def test_a_stale_snapshot_is_served_while_another_thread_refreshes(self, keyed_db, monkeypatch):
        db = keyed_db
        put(db, "sm_ai.chat_model", "first")
        monkeypatch.setattr(constants, "LAZY_SETTINGS_TTL_SECONDS", 0.0)
        assert resolve_model().model_name == "first"  # cached, already stale
        put(db, "sm_ai.chat_model", "second")

        assert worker_settings._refresh.acquire(blocking=False)  # someone is reading
        try:
            assert resolve_model().model_name == "first"  # served stale, did not block
        finally:
            worker_settings._refresh.release()
        assert resolve_model().model_name == "second"

    def test_the_snapshot_repr_hides_the_secret(self, db):
        put(db, "host.secret_key", DB_SECRET)
        services.current_settings()
        assert DB_SECRET not in repr(worker_settings._snapshot)

    def test_a_forked_child_starts_with_free_locks_and_no_cache(self, db):
        services.current_settings()
        worker_settings._refresh.acquire()  # the parent forked mid-refresh
        worker_settings._after_fork_in_child()
        assert worker_settings._snapshot is None
        assert worker_settings._refresh.acquire(blocking=False)
        worker_settings._refresh.release()


class TestWebHostUnchanged:
    def test_installed_holder_is_used_and_db_never_read(self, monkeypatch):
        def boom():
            raise AssertionError("the web path must not hydrate lazily")

        monkeypatch.setattr(worker_settings, "_hydrate", boom)
        monkeypatch.setenv("SM_SECRET_KEY", "web-secret")
        installed = services.install(
            services.AiServices(
                settings=AiSettings(chat_model="from-holder", chat_api_key="sk-plain")
            )
        )

        assert services.current_settings() is installed.settings
        assert resolve_model().model_name == "from-holder"

    def test_hosts_secret_provider_is_never_displaced(self, db):
        def live() -> str:
            return "live-app-secret"

        crypto.set_secret_provider(live)
        services.current_settings()
        assert crypto._secret_provider is live
