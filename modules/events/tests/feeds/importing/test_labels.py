"""Every code the import can report has a label in every catalogue, and no label is orphaned."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import sm_events
from sm_events.core import constants

ROOT = Path(sm_events.__file__).parent
LOCALES = ("en", "de")


def _catalogue(locale: str) -> dict:
    return json.loads((ROOT / "locales" / f"{locale}.json").read_text())["import"]


def _raised_codes() -> set[str]:
    """The failure codes written in the importer's source (a literal at a raise site)."""
    found: set[str] = set()
    for path in (ROOT / "feeds" / "importing").glob("*.py"):
        text = path.read_text()
        found |= set(re.findall(r'ImportFailure\(\s*"(\w+)"', text))
        found |= {c for c in constants.IMPORT_FAILURE_CODES if f'"{c}"' in text}
    found |= {constants.IMPORTER_GONE, constants.ICS_INVALID_CODE}
    return found


def test_every_raised_failure_code_is_a_known_one():
    assert _raised_codes() <= set(constants.IMPORT_FAILURE_CODES)


@pytest.mark.parametrize("locale", LOCALES)
def test_failure_and_outcome_labels_match_the_codes_exactly(locale):
    catalogue = _catalogue(locale)
    assert set(catalogue["failure"]) == set(constants.IMPORT_FAILURE_CODES)
    assert set(catalogue["outcome"]) == set(constants.ITEM_OUTCOMES)


@pytest.mark.parametrize("locale", LOCALES)
def test_every_skip_reason_the_server_names_has_a_label(locale):
    reasons = set(_catalogue(locale)["reasons"])
    literal = set()
    for path in (ROOT / "feeds" / "importing").glob("*.py"):
        literal |= set(re.findall(r'(?:ItemSkip|note)\(\s*"(\w+)"', path.read_text()))
    assert literal <= reasons, literal - reasons
