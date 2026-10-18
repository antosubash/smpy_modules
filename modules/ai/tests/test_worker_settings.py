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
