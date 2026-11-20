"""The public surface's tests run at one fixed "now", well inside the seeded fixture's year."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.core import clock
from sm_events.web.endpoints.public import _private_feed

NOW = datetime(2026, 4, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: NOW)


@pytest.fixture(autouse=True)
def _fresh_token_throttle():
    """The per-token window is process-wide state; no test may inherit another's hits."""
    _private_feed.THROTTLE.clear()
    yield
    _private_feed.THROTTLE.clear()
