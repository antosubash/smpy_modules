"""The worker's secret resolver (S11): env, .env, stored row, else refuse."""

from __future__ import annotations

import pytest
from background_tasks import sync_db
from simple_module_db.stored_settings import Setting
from sm_newsletter.core import crypto, secret, tokens
from sm_newsletter.core.errors import SmtpPasswordUnreadable
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.pg_support import USING_POSTGRES
from tests.support.worker_env import isolate_worker_env, reset_worker_caches

pytestmark = pytest.mark.skipif(
    USING_POSTGRES, reason="the worker secret test points sync_db at its own SQLite file"
)


def _enc(plain: str, under: str) -> str:
    return crypto.ENC_PREFIX + crypto._fernet_for(under).encrypt(plain.encode()).decode()


@pytest.fixture
def clean(tmp_path, monkeypatch):
    isolate_worker_env(monkeypatch, tmp_path)
    yield tmp_path
    reset_worker_caches()


@pytest.fixture
def db(clean):
    """A SQLite file with the settings table, reached through ``sync_db``."""
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
    assert crypto.decrypt_value(_enc("pw", resolved), "smtp_password") == "pw"
    token = tokens.sign(resolved, tenant_id="default", campaign_id=1, send_id=2)
    assert tokens.parse(resolved, token) is not None


def test_env_and_stored_row_env_wins(db, monkeypatch):
    db("row-secret")
    monkeypatch.setenv("SM_SECRET_KEY", "env-secret")
    assert secret.resolve_worker_secret() == "env-secret"
    _check("env-secret")
    assert (
        tokens.parse(
            "row-secret", tokens.sign("env-secret", tenant_id="default", campaign_id=1, send_id=2)
        )
        is None
    )


def test_env_only(db, monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", "env-secret")
    assert secret.resolve_worker_secret() == "env-secret"
    _check("env-secret")


def test_stored_row_only(db):
    db("row-secret")
    assert secret.resolve_worker_secret() == "row-secret"
    _check("row-secret")


def test_neither_refuses(db):
    with pytest.raises(secret.SecretMissing) as info:
        secret.resolve_worker_secret()
    assert "secret" not in str(info.value).replace("secret key", "").replace("host.secret_key", "")


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
    with pytest.raises(SmtpPasswordUnreadable):
        crypto.decrypt_value(_enc("pw", "other"), "smtp_password")


def test_install_keeps_an_app_provider(clean, monkeypatch):
    crypto.set_secret_provider(lambda: "app-secret")
    secret.install("worker-secret")
    assert crypto._secret_provider() == "app-secret"
