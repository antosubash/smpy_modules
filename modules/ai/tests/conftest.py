"""Hermetic environment for the module suite (stubs live in ai_test_stubs).

``AiSettings`` reads no environment (#124), but the crypto fallback reads
``SM_SECRET_KEY`` from the process environment *and* the project ``.env``
(found from ``SM_PROJECT_ROOT`` or by walking up from the cwd). A developer
dogfooding this module will have both, so every test runs with the host env
scrubbed and cwd moved to an empty tmp dir. Stray ``SM_AI_*`` variables are
scrubbed too, so a test asserting they are ignored cannot pass by accident.
The live-secret provider is reset per test; the Fernet cache is keyed by
secret, so rotated secrets never see stale entries.
"""

from __future__ import annotations

import os

import pytest
from ai_worker_support import put
from settings.models import Setting
from sm_ai import crypto, services
from sqlmodel import create_engine


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch, tmp_path):
    for var in [k for k in os.environ if k.startswith("SM_AI_")]:
        monkeypatch.delenv(var)
    monkeypatch.delenv("SM_SECRET_KEY", raising=False)
    monkeypatch.delenv("SM_PROJECT_ROOT", raising=False)
    monkeypatch.setattr(crypto, "_secret_provider", None)
    monkeypatch.chdir(tmp_path)
    # The .env fallback is cached per process; each test gets its own cwd, so
    # a value cached under another test's tmp dir must not leak in.
    crypto._dotenv_secret.cache_clear()
    yield


# --- the worker path (test_worker_settings*): no app, no registered module ---


@pytest.fixture
def worker_env(monkeypatch, tmp_path):
    for var in ("SM_DATABASE_URL", "SM_PROJECT_ROOT"):
        monkeypatch.delenv(var, raising=False)
    # Set, and ignored: a test passing because of it would show the bug back.
    monkeypatch.setenv("SM_AI_CHAT_API_KEY", "sk-plain-env")
    monkeypatch.setenv("SM_AI_CHAT_MODEL", "from-env")
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


@pytest.fixture
def keyed_db(db):
    """A database with a plaintext key row, so tests about where the *model*
    comes from need not each encrypt one; a test's own row replaces it."""
    put(db, "sm_ai.chat_api_key", "sk-plain-db")
    return db
