"""The limits table in docs/blocks.md is the constants' own values, so it cannot drift."""

from __future__ import annotations

import re
from pathlib import Path

from sm_events.core import constants

DOC = Path(__file__).resolve().parents[3] / "docs" / "blocks.md"


def _rows() -> list[tuple[list[str], list[str]]]:
    rows = []
    for line in DOC.read_text().splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 3 and cells[2].startswith("`") and cells[0] != "Limit":
            names = re.findall(r"`([A-Z_]+)`", cells[2])
            rows.append(([v.strip("`") for v in cells[1].split(" / ")], names))
    return rows


def test_each_value_in_the_table_matches_its_constant():
    rows = _rows()
    assert len(rows) >= 6
    for values, names in rows:
        assert len(values) == len(names), names
        for value, name in zip(values, names, strict=True):
            actual = getattr(constants, name)
            assert str(actual) == value, name


def test_the_table_and_the_constants_name_each_other():
    """Both ways: every constant a block or a card obeys is in the table, and every name in the
    table is a constant."""
    named = {n for _, names in _rows() for n in names}
    ruled = {
        n
        for n in dir(constants)
        if n.startswith(("UPCOMING_BLOCK_", "BLOCK_", "CARD_"))
        or n in {"PUBLIC_BLOCKS_API", "MAX_EVENT_SEARCH_LIMIT"}
    }
    assert ruled == named, ruled ^ named


def _card_fields_in_the_doc() -> set[str]:
    text = DOC.read_text()
    start = text.index("**The fields of a card**")
    paragraph = text[start : text.index("\n\n", start)]
    return {n for n in re.findall(r"`([^`]*)`", paragraph) if re.fullmatch(r"[a-z_]+", n)} - {
        "none"
    }


def test_the_card_fields_in_the_doc_are_the_cards_both_ways():
    from sm_events.contracts.cards import EventCard

    assert _card_fields_in_the_doc() == set(EventCard.model_fields)


UI = Path(__file__).resolve().parents[3] / "sm_events" / "ui" / "blocks"


def _ts_type_keys(file: str, name: str) -> set[str]:
    source = (UI / file).read_text()
    body = source[source.index(f"export type {name} = {{") :].split("};", 1)[0]
    return set(re.findall(r"^  (\w+)\??:", body, re.MULTILINE))


def _doc_props(block: str) -> set[str]:
    for line in DOC.read_text().splitlines():
        if line.startswith(f"| `{block}` |"):
            cell = line.split("|")[2]
            # The values in parentheses are not props.
            return set(re.findall(r"`(\w+)`", re.sub(r"\([^)]*\)", "", cell)))
    raise AssertionError(block)


def test_the_block_props_in_the_doc_are_the_blocks_both_ways():
    assert _doc_props("UpcomingEvents") == _ts_type_keys(
        "UpcomingEventsRender.tsx", "UpcomingEventsProps"
    )
    assert _doc_props("EventsCalendar") == _ts_type_keys("calendarProps.ts", "EventsCalendarProps")
