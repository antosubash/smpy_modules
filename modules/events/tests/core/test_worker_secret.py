"""The worker's secret resolver: env, .env, stored row, else refuse; a worker never creates one."""

from __future__ import annotations

import pytest
from background_tasks.core import sync_db
from background_tasks.worker.settings import clear_settings_cache
from simple_module_db.stored_settings import Setting
from sm_events.core import crypto, secret
from sm_events.core.errors_subscriptions import SecretUnreadable
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.pg_support import USING_POSTGRES

pytestmark = pytest.mark.skipif(
    USING_POSTGRES, reason="the worker secret test points sync_db at its own SQLite file"
)


def _reset() -> None:
    crypto._dotenv_secret.cache_clear()
    crypto._dotenv_previous.cache_clear()
    clear_settings_cache()


def _encrypted(plain: str, under: str) -> str:
    return crypto.ENC_V2 + crypto._keys((under,), crypto.ENC_V2).encrypt(plain.encode()).decode()


@pytest.fixture
def clean(tmp_path, monkeypatch):
    monkeypatch.setenv("SM_PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("SM_SECRET_KEY", raising=False)
    monkeypatch.delenv("SM_SECRET_KEY_PREVIOUS", raising=False)
    monkeypatch.setattr(crypto, "_secret_provider", None)
    _reset()
    yield tmp_path
    _reset()


@pytest.fixture
def db(clean):
    url = f"sqlite:///{clean / 'w.db'}"
    engine = create_engine(url)
    Setting.__table__.create(engine)

    def put(value: str) -> None:
        with Session(engine) as s:
            s.add(Setting(key="host.secret_key", value=value))
            s.commit()

    sync_db.set_database_url(url)
    yield put
    sync_db.set_database_url(None)
    sync_db.dispose_sync_engine()
    engine.dispose()


def _check(resolved: str) -> None:
    secret.install(resolved)
    assert crypto.decrypt_value(_encrypted("https://x/p", resolved), "url") == "https://x/p"


def test_env_wins_over_the_stored_row(db, monkeypatch):
    db("row-secret")
    monkeypatch.setenv("SM_SECRET_KEY", "env-secret")
    assert secret.resolve_worker_secret() == "env-secret"
    _check("env-secret")


def test_stored_row_only(db):
    db("row-secret")
    assert secret.resolve_worker_secret() == "row-secret"
    _check("row-secret")


def test_neither_refuses_and_creates_nothing(db, clean):
    with pytest.raises(secret.SecretMissing):
        secret.resolve_worker_secret()
    engine = create_engine(f"sqlite:///{clean / 'w.db'}")
    with Session(engine) as session:
        assert session.query(Setting).count() == 0  # a worker never stores a key
    engine.dispose()


def test_an_unreadable_database_counts_as_no_row(clean):
    sync_db.set_database_url(f"sqlite:///{clean / 'missing' / 'nope.db'}")
    try:
        with pytest.raises(secret.SecretMissing):
            secret.resolve_worker_secret()
    finally:
        sync_db.set_database_url(None)
        sync_db.dispose_sync_engine()


def test_wrong_secret_never_yields_plaintext(db, monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", "env-secret")
    secret.install(secret.resolve_worker_secret())
    with pytest.raises(SecretUnreadable):
        crypto.decrypt_value(_encrypted("p", "other"), "url")


def test_install_keeps_an_app_provider(clean):
    crypto.set_secret_provider(lambda: "app-secret")
    secret.install("worker-secret")
    assert crypto._secret_provider() == "app-secret"
