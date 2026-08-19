"""Hermetic environment for the module suite (stubs live in ai_test_stubs).

``AiSettings`` and ``_CryptoEnv`` read ``SM_AI_*`` / ``SM_SECRET_KEY`` from
the process environment *and* a ``.env`` in the working directory. A
developer dogfooding this module will have both, so every test runs with the
host env scrubbed and cwd moved to an empty tmp dir. The Fernet cache and
the live-secret provider are cleared around each test because several tests
rotate the secret.
"""

from __future__ import annotations

import os

import pytest
from sm_ai import crypto


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch, tmp_path):
    for var in [k for k in os.environ if k.startswith("SM_AI_")]:
        monkeypatch.delenv(var)
    monkeypatch.delenv("SM_SECRET_KEY", raising=False)
    monkeypatch.setattr(crypto, "_secret_provider", None)
    monkeypatch.chdir(tmp_path)
    crypto._fernet.cache_clear()
    yield
    crypto._fernet.cache_clear()
