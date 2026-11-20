"""The limits table in docs/subscriptions.md is the constants' own values, both ways."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from sm_events.core import constants

DOC = Path(__file__).resolve().parents[3] / "docs" / "subscriptions.md"
UNITS = {"s": 1, "minutes": 60, "hours": 3600, "days": 86400, "MiB": 1024**2}


def _number(text: str) -> float:
    found = re.fullmatch(r"([\d,]+)(?: (s|minutes|hours|days|MiB))?", text.strip())
    assert found, text
    return float(found.group(1).replace(",", "")) * UNITS.get(found.group(2) or "", 1)


def _rows() -> list[tuple[list[float], list[str]]]:
    rows = []
    for line in DOC.read_text().splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 3 and cells[2].startswith("`") and cells[0] != "Limit":
            names = re.findall(r"`([A-Z_]+)`", cells[2])
            values = [v.strip() for v in re.split(r" / ", cells[1])]
            # "15 / 1,440 minutes": the unit closes the list
            unit = re.search(r"(minutes|s|hours|days|MiB)$", values[-1])
            parsed = [
                _number(v if re.search(r"[a-zA-Z]$", v) else f"{v} {unit.group(1)}")
                if unit
                else _number(v)
                for v in values
            ]
            rows.append((parsed, names))
    return rows


def _as_number(value: object) -> float:
    return value.total_seconds() if isinstance(value, timedelta) else float(value)  # type: ignore[arg-type]


def test_each_value_in_the_table_matches_its_constant():
    rows = _rows()
    assert len(rows) >= 20
    for values, names in rows:
        assert len(values) == len(names), names
        for value, name in zip(values, names, strict=True):
            actual = _as_number(getattr(constants, name))
            if name.endswith("_DAYS"):
                actual *= 86400
            if name.endswith("_MINUTES"):
                actual *= 60
            assert actual == value, name


def test_the_table_names_every_bound_that_matters():
    named = {n for _, names in _rows() for n in names}
    assert {
        "SUBSCRIPTION_FETCH_SECONDS",
        "SUBSCRIPTION_MAX_REDIRECTS",
        "SUBSCRIPTION_ITEMS_MAX",
        "SUBSCRIPTIONS_PER_CALENDAR",
        "SUBSCRIPTION_MIN_REFRESH_MINUTES",
        "SUBSCRIPTION_REFRESH_NOW_SECONDS",
        "SUBSCRIPTION_MAX_FAILURES",
        "SUBSCRIPTION_TICK_FETCHES",
        "SUBSCRIPTION_LEASE",
        "SUBSCRIPTION_MAX_CONCURRENT_FETCHES",
        "SUBSCRIPTION_MAX_CONCURRENT_FETCHES_PER_TENANT",
    } <= named


def test_every_failure_code_is_documented():
    text = DOC.read_text()
    for code in constants.SUBSCRIPTION_FAILURE_CODES:
        assert f"`{code}`" in text, code
