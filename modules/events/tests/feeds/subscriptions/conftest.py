"""A known secret for every subscription test: the stored-secret crypto reads it through the
provider, as a running app would install it."""

from __future__ import annotations

import pytest
from sm_events.core import crypto

SECRET = "subscription-test-secret"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(crypto, "_secret_provider", lambda: SECRET)
    monkeypatch.delenv("SM_SECRET_KEY_PREVIOUS", raising=False)
    crypto._dotenv_previous.cache_clear()
    yield
    crypto._dotenv_previous.cache_clear()
