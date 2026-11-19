"""The limits table in docs/import.md is the constants' own values, so it cannot drift."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from sm_events.core import constants

DOC = Path(__file__).resolve().parents[3] / "docs" / "import.md"
UNITS = {"KiB": 1024, "MiB": 1024**2, "s": 1, "hour": 3600, "hours": 3600}


def _number(text: str) -> float:
    found = re.fullmatch(r"([\d,]+(?:\.\d+)?)(?: (KiB|MiB|s|hours?|deep))?", text.strip())
    assert found, text
    value = float(found.group(1).replace(",", ""))
    return value * UNITS.get(found.group(2) or "", 1)


def _rows() -> list[tuple[list[float], list[str]]]:
    rows = []
    for line in DOC.read_text().splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 3 and cells[2].startswith("`") and cells[0] != "Limit":
            names = re.findall(r"`([A-Z_]+)`", cells[2])
            rows.append(([_number(v) for v in cells[1].split(" / ")], names))
    return rows


def _as_number(value: object) -> float:
    return value.total_seconds() if isinstance(value, timedelta) else float(value)  # type: ignore[arg-type]


def test_each_value_in_the_table_matches_its_constant():
    rows = _rows()
    assert len(rows) >= 14
    for values, names in rows:
        assert len(values) == len(names), names
        for value, name in zip(values, names, strict=True):
            assert _as_number(getattr(constants, name)) == value, name


def test_the_table_lists_the_limits_that_bound_an_upload():
    named = {n for _, names in _rows() for n in names}
    assert {
        "IMPORT_MAX_EVENTS",
        "IMPORT_MAX_ATTENDEES",
        "IMPORT_DESCRIPTION_MAX",
        "IMPORT_GRANTS_TTL",
        "IMPORT_TTL",
        "IMPORT_ACTIVE_MAX",
    } <= named
