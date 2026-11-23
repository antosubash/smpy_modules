"""Every code the Reminders UI can show has a label in every catalogue, and no label is orphaned.

The UI keeps two tables (``ui/reminders/reasons.ts``); this ties them to the server's codes and to
``locales/<locale>.json`` both ways, as the import's ``test_labels.py`` does."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import sm_events
from sm_events.core import constants

ROOT = Path(sm_events.__file__).parent
LOCALES = ("en", "de")
TABLES = (ROOT / "ui" / "reminders" / "reasons.ts").read_text()
FAILED_CODES = (
    constants.REMINDER_SEND_FAILED,
    constants.REMINDER_CODE_SEND_TIMEOUT,
    constants.REMINDER_CODE_TOO_LATE,
)


def _table(name: str) -> dict[str, str]:
    body = re.search(rf"export const {name}[^=]*= \{{(.*?)\n\}};", TABLES, re.S)
    assert body, name
    return dict(re.findall(r"(\w+): delivery\.(\w+)", body.group(1)))


def _delivery(locale: str) -> dict:
    path = ROOT / "locales" / f"{locale}.json"
    return json.loads(path.read_text(encoding="utf-8"))["reminders"]["delivery"]


def test_the_reason_table_is_the_servers_codes_and_each_maps_to_its_own_key():
    table = _table("AVAILABILITY_REASONS")
    assert set(table) == set(constants.AVAILABILITY_REASONS)
    assert table == {code: f"reason_{code}" for code in table}


def test_the_failure_table_is_the_ledgers_codes_and_each_maps_to_its_own_key():
    table = _table("FAILED_CODES")
    assert set(table) == set(FAILED_CODES)
    assert table == {code: f"failed_code_{code}" for code in table}


@pytest.mark.parametrize("locale", LOCALES)
def test_the_catalogue_has_exactly_these_labels(locale):
    keys = set(_delivery(locale))
    reasons = {k.removeprefix("reason_") for k in keys if k.startswith("reason_")}
    failed = {k.removeprefix("failed_code_") for k in keys if k.startswith("failed_code_")}
    assert reasons == set(constants.AVAILABILITY_REASONS)
    assert failed == set(FAILED_CODES)
