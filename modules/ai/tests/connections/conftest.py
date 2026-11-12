"""Shared set-up for the connection tests: a secret key and a clean holder.

Every test here may encrypt a key (``crypto.encrypt_value``) or install
settings in the module-global holder; this gives each one the secret and
resets the holder afterwards. A directory conftest, as newsletter's suites use:
the package ``__init__.py`` files keep it from colliding with another suite's.
"""

from __future__ import annotations

import pytest
from sm_ai.core import services

SECRET = "test-secret-key-for-connections"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    yield
    services.reset()
