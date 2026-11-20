"""The limits table in docs/subscriptions.md is the constants' own values, both ways."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from sm_events.core import constants

DOC = Path(__file__).resolve().parents[3] / "docs" / "subscriptions.md"
UNITS = {
    "s": 1,
    "minutes": 60,
    "hours": 3600,
    "days": 86400,
    "KiB": 1024,
    "MiB": 1024**2,
    "per minute": 1,
}


def _number(text: str) -> float:
    found = re.fullmatch(r"([\d,]+)(?: (s|minutes|hours|days|KiB|MiB|per minute))?", text.strip())
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
            unit = re.search(r"(minutes|s|hours|days|KiB|MiB)$", values[-1])
            parsed = [
                _number(v if re.search(r"[a-zA-Z]$", v) else f"{v} {unit.group(1)}")
                if unit
                else _number(v)
                for v in values
            ]
            rows.append((parsed, names))
    return rows


def _as_number(value: object) -> float:
    if isinstance(value, str):  # a rate: "20/minute" is the number 20
        return float(value.split("/")[0])
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


# Numeric constants that are not limits a reader tunes or meets: column widths (what the schema
# stores), the store's internal batch size, and the failure vocabulary's strings.
NOT_LIMITS = {
    "SUBSCRIPTION_CODE_MAX",
    "SUBSCRIPTION_ETAG_MAX",
    "SUBSCRIPTION_LAST_MODIFIED_MAX",
    "SUBSCRIPTION_LEASE_OWNER_MAX",
    "SUBSCRIPTION_STATUS_MAX",
    "SUBSCRIPTION_VERSION_MAX",
    "URL_DISPLAY_MAX",
    "SUBSCRIPTION_STORE_CHUNK",
}


def test_every_limit_constant_is_in_the_table_and_every_row_has_a_constant():
    from sm_events.core.constants import subscriptions as module

    named = {n for _, names in _rows() for n in names}
    limits = {
        n
        for n in dir(module)
        if (
            n.isupper()
            and not n.startswith("_")
            and isinstance(getattr(module, n), (int, float, timedelta))
            and not isinstance(getattr(module, n), bool)
        )
        or n == "SUBSCRIPTION_WRITE_RATE"
    } - NOT_LIMITS
    assert limits - named == set(), "a limit the table does not state"
    assert named - set(dir(constants)) == set(), "a row that names no constant"
    assert set(dir(module)) >= NOT_LIMITS, "an exemption for a constant that is gone"


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
