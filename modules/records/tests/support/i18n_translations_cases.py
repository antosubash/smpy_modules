"""Shared setup for test_i18n_translations."""

from __future__ import annotations
from sm_records.core.settings import RecordsSettings
from tests.support.app_harness import ADMIN, ROLE_EDITOR, ROLE_EDITOR_TWO, roles
from tests.support.i18n_helpers import API, TYPE_KEY, make_record, make_type, publish, set_type, translate
