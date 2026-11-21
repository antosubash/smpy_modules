"""``docs/reminders.md`` states every bound reminders have, and the table is the constants'."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from sm_events.core.constants import reminders_limits as limits

DOC = Path(__file__).resolve().parents[2] / "docs" / "reminders.md"
ROW = re.compile(r"^\| `([A-Z_]+)` \| ([^|]+?) \|", re.MULTILINE)


def _render(value) -> str:
    if isinstance(value, timedelta):
        seconds = int(value.total_seconds())
        return f"{seconds} s"
    if isinstance(value, dict):
        return ", ".join(f"{lead}: {_render(span)}" for lead, span in sorted(value.items()))
    if isinstance(value, tuple):
        return ", ".join(str(v) for v in value)
    return str(value)


def _documented() -> dict[str, str]:
    return {name: text.strip() for name, text in ROW.findall(DOC.read_text(encoding="utf-8"))}


def test_every_limit_is_in_the_table_with_its_value():
    doc = _documented()
    constants = {name: getattr(limits, name) for name in limits.__all__}
    assert set(constants) <= set(doc), sorted(set(constants) - set(doc))
    for name, value in constants.items():
        assert doc[name] == _render(value), (name, doc[name], _render(value))


def test_the_table_names_nothing_that_is_gone():
    assert set(_documented()) <= set(limits.__all__)


def test_the_doc_states_the_limits_that_matter_in_words():
    text = DOC.read_text(encoding="utf-8")
    for phrase in (
        "at most once",
        "#1005",
        "is not retried",
        "cannot be detected",
        "public_base_url",
        "never provisions a secret key",
        "counts only",
    ):
        assert phrase in text, phrase
