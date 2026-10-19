"""``resolve_model()`` outside the web host — a Celery worker's view (#100).

Nothing here builds an app or registers the module: that is the whole point.
A worker imports consumer code and calls ``sm_ai.contracts`` with an empty
holder, so settings must come from the shared settings table (and the secret
the web app encrypted keys under) or from ``SM_AI_*`` env.

Celery itself is not a test dependency and framework 0.0.35 ships no
``background_tasks`` package, so the "task" is a plain function run on a
fresh thread — both ways a task body commonly reaches the contract (sync, and
inside its own ``asyncio.run``) are covered.
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from pydantic_ai.models.anthropic import AnthropicModel
from settings.models import Setting
from sm_ai import constants, crypto, services, worker_settings
from sm_ai.contracts import resolve_model
from sm_ai.settings import AiSettings
from sqlmodel import Session, create_engine, select

DB_SECRET = "generated-and-stored-by-the-web-host"


@pytest.fixture(autouse=True)
def _worker(monkeypatch, tmp_path):
    for var in ("SM_DATABASE_URL", "SM_PROJECT_ROOT"):
        monkeypatch.delenv(var, raising=False)
    # A plaintext env key, so tests about where the *model* comes from need
    # not each encrypt one; the DB row beats it wherever a test stores one.
    monkeypatch.setenv("SM_AI_CHAT_API_KEY", "sk-plain-env")
    services.reset()
    yield
    services.reset()


@pytest.fixture
def db(monkeypatch, tmp_path):
    path = tmp_path / "worker.db"
    engine = create_engine(f"sqlite:///{path}")
    Setting.__table__.create(engine)
    monkeypatch.setenv("SM_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    yield engine
    engine.dispose()


def _put(engine, key: str, value: str, value_type: str = "string") -> None:
    with Session(engine) as s:
        row = s.exec(select(Setting).where(Setting.key == key)).first()
        if row is None:
            row = Setting(key=key, value=value, value_type=value_type)
        row.value = value
        s.add(row)
        s.commit()


def _encrypt_as_web_host(plain: str) -> str:
    crypto.set_secret_provider(lambda: DB_SECRET)
    try:
        return crypto.encrypt_value(plain)
    finally:
        crypto._secret_provider = None


def _task():
    """What a ``@shared_task`` body does: resolve, on a worker thread."""
    out: dict = {}

    def run():
        try:
            out["model"] = resolve_model()
        except BaseException as exc:  # surfaced to the test below
            out["error"] = exc

    t = threading.Thread(target=run)
    t.start()
    t.join()
    if "error" in out:
        raise out["error"]
    return out["model"]


def _key(model: AnthropicModel) -> str:
    return model.client.api_key


class TestDbStoredSettings:
    def test_resolves_with_db_values_and_the_hosts_stored_secret(self, db, monkeypatch):
        monkeypatch.setenv("SM_AI_CHAT_MODEL", "from-env")
        _put(db, "host.secret_key", DB_SECRET)
        _put(db, "sm_ai.chat_model", "from-db")
        _put(db, "sm_ai.chat_api_key", _encrypt_as_web_host("sk-db"))

        model = _task()

        assert isinstance(model, AnthropicModel)
        assert model.model_name == "from-db"  # DB beats env, as on the web
        assert _key(model) == "sk-db"

    def test_typed_rows_are_parsed(self, db):
        _put(db, "sm_ai.embedding_dim", "1536", "int")
        assert services.current_settings().embedding_dim == 1536

    def test_explicit_env_secret_beats_the_stored_one(self, db, monkeypatch):
        monkeypatch.setenv("SM_SECRET_KEY", "explicit-env-secret")
        _put(db, "host.secret_key", DB_SECRET)
        crypto.set_secret_provider(lambda: "explicit-env-secret")
        stored = crypto.encrypt_value("sk-env-secret")
        crypto._secret_provider = None
        _put(db, "sm_ai.chat_api_key", stored)

        assert _key(_task()) == "sk-env-secret"

    def test_inside_a_running_event_loop(self, db):
        # Tasks that drive an agent call asyncio.run(...) and resolve inside
        # it; the hydration read must not try to nest a loop.
        _put(db, "sm_ai.chat_model", "from-db")

        async def body():
            return resolve_model()

        assert asyncio.run(body()).model_name == "from-db"


class TestEnvOnlySettings:
    def test_migrated_but_empty_table(self, db, monkeypatch):
        monkeypatch.setenv("SM_SECRET_KEY", "env-secret")
        monkeypatch.setenv("SM_AI_CHAT_MODEL", "from-env")

        model = _task()

        assert model.model_name == "from-env"
        assert _key(model) == "sk-plain-env"

    def test_unreachable_database_falls_back_to_env(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setenv("SM_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/no/such/dir.db")
        monkeypatch.setenv("SM_AI_CHAT_MODEL", "from-env")

        assert _task().model_name == "from-env"
        assert "database read failed" in caplog.text

    def test_the_fallback_warning_never_carries_the_database_url(self, monkeypatch, caplog):
        # A refused connection: drivers put host, user — sometimes the whole
        # URL — in the message and the traceback. None of it may reach a log.
        url = "postgresql+asyncpg://admin:hunter2-secret@127.0.0.1:1/ai"
        monkeypatch.setenv("SM_DATABASE_URL", url)

        _task()

        assert "database read failed" in caplog.text
        assert "hunter2-secret" not in caplog.text
        assert "admin" not in caplog.text
        assert all(record.exc_info is None for record in caplog.records)


class TestCache:
    def test_cached_until_invalidated(self, db):
        _put(db, "sm_ai.chat_model", "first")
        assert resolve_model().model_name == "first"

        _put(db, "sm_ai.chat_model", "second")
        assert resolve_model().model_name == "first"  # per-process cache

        services.invalidate()
        assert resolve_model().model_name == "second"

    def test_ttl_expiry_rereads(self, db, monkeypatch):
        # The only cross-process path a console save has to a worker.
        monkeypatch.setattr(constants, "LAZY_SETTINGS_TTL_SECONDS", 0.0)
        _put(db, "sm_ai.chat_model", "first")
        assert resolve_model().model_name == "first"

        _put(db, "sm_ai.chat_model", "second")
        assert resolve_model().model_name == "second"

    def test_one_read_per_ttl(self, db, monkeypatch):
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
        monkeypatch.setenv("SM_AI_CHAT_MODEL", "from-env")
        assert resolve_model().model_name == "from-env"  # no database yet

        engine = create_engine(f"sqlite:///{path}")
        Setting.__table__.create(engine)
        _put(engine, "sm_ai.chat_model", "from-db")
        engine.dispose()
        assert resolve_model().model_name == "from-db"  # the 60s TTL did not apply

    def test_a_missing_sqlite_file_is_not_created(self, monkeypatch, tmp_path):
        path = tmp_path / "never.db"
        monkeypatch.setenv("SM_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
        resolve_model()
        assert not path.exists()

    def test_the_warning_is_logged_once_per_outage(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setenv("SM_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/gone.db")
        monkeypatch.setattr(constants, "LAZY_SETTINGS_RETRY_SECONDS", 0.0)
        for _ in range(3):
            resolve_model()
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1

    def test_a_hung_read_is_bounded(self, db, monkeypatch):
        async def hang(_url):
            await asyncio.sleep(30)

        monkeypatch.setattr(worker_settings, "_read", hang)
        monkeypatch.setattr(constants, "LAZY_SETTINGS_READ_TIMEOUT_SECONDS", 0.1)
        monkeypatch.setenv("SM_AI_CHAT_MODEL", "from-env")
        assert _task().model_name == "from-env"

    def test_a_stale_snapshot_is_served_while_another_thread_refreshes(self, db, monkeypatch):
        _put(db, "sm_ai.chat_model", "first")
        monkeypatch.setattr(constants, "LAZY_SETTINGS_TTL_SECONDS", 0.0)
        assert resolve_model().model_name == "first"  # cached, already stale
        _put(db, "sm_ai.chat_model", "second")

        assert worker_settings._refresh.acquire(blocking=False)  # someone is reading
        try:
            assert resolve_model().model_name == "first"  # served stale, did not block
        finally:
            worker_settings._refresh.release()
        assert resolve_model().model_name == "second"

    def test_the_snapshot_repr_hides_the_secret(self, db):
        _put(db, "host.secret_key", DB_SECRET)
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
            services.AiServices(settings=AiSettings(chat_model="from-holder"))
        )

        assert services.current_settings() is installed.settings
        assert resolve_model().model_name == "from-holder"

    def test_hosts_secret_provider_is_never_displaced(self, db):
        def live() -> str:
            return "live-app-secret"

        crypto.set_secret_provider(live)
        services.current_settings()
        assert crypto._secret_provider is live
