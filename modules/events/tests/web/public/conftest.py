"""The public surface's tests run at one fixed "now", well inside the seeded fixture's year."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.web.endpoints.public import _clock

NOW = datetime(2026, 4, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr(_clock, "now", lambda: NOW)
