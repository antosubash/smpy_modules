"""Hermetic environment for the module suite (stubs live in ai_test_stubs).

``AiSettings`` and ``_CryptoEnv`` read ``SM_AI_*`` / ``SM_SECRET_KEY`` from
the process environment *and* a ``.env`` in the working directory. A
developer dogfooding this module will have both, so every test runs with the
host env scrubbed and cwd moved to an empty tmp dir. The live-secret
provider is reset per test; the Fernet cache is keyed by secret, so rotated
secrets never see stale entries.
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
    yield
