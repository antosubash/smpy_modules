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


def test_the_table_names_the_bounds_a_block_and_a_card_obey():
    named = {n for _, names in _rows() for n in names}
    assert {
        "PUBLIC_BLOCKS_API",
        "UPCOMING_BLOCK_MAX",
        "UPCOMING_BLOCK_DEFAULT",
        "BLOCK_CALENDARS_MAX",
        "MAX_EVENT_SEARCH_LIMIT",
        "CARD_SEARCH_SCAN",
        "CARD_READ_ROUNDS",
    } <= named


def test_the_card_fields_in_the_doc_are_the_cards():
    from sm_events.contracts.cards import EventCard

    text = DOC.read_text()
    for name in EventCard.model_fields:
        assert f"`{name}`" in text, name


def test_the_block_props_in_the_doc_are_the_blocks():
    text = DOC.read_text()
    for prop in (
        "heading",
        "calendars",
        "category",
        "count",
        "layout",
        "showImages",
        "defaultView",
        "height",
    ):
        assert f"`{prop}`" in text, prop
