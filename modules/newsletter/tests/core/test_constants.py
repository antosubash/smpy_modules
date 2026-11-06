"""Constants newsletter mirrors from another module stay equal to it (G16)."""

from __future__ import annotations

from sm_newsletter.core import constants
from sm_records.core import constants as records_constants


def test_records_view_permission_is_records_own():
    assert constants.PERM_RECORDS_VIEW == records_constants.PERM_VIEW
