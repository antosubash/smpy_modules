"""The ICS dependency's licence, and the one we refuse."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_no_lgpl_recurrence_package():
    lock = (ROOT / "uv.lock").read_text()
    assert 'name = "recurring-ical-events"' not in lock
    assert 'name = "icalendar"' in lock


def test_icalendar_is_bsd():
    meta = importlib.metadata.metadata("icalendar")
    text = " ".join(
        [
            meta.get("License", ""),
            meta.get("License-Expression", ""),
            *meta.get_all("Classifier", []),
        ]
    )
    assert "BSD" in text


def test_events_declares_it_as_a_range():
    deps = (ROOT / "modules/events/pyproject.toml").read_text()
    line = next(ln for ln in deps.splitlines() if "icalendar" in ln)
    assert ">=7,<8" in line and "# floor:" in line and "==" not in line
