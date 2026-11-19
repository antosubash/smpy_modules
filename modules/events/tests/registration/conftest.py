"""Fixtures of the registration tests."""

from __future__ import annotations

import pytest

from tests.registration.support import public_calendar


@pytest.fixture
async def cal(db):
    """A public calendar to put events on."""
    return await public_calendar(db)
