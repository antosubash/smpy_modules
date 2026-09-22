"""The schema editor's mirrors of the API's key rules must equal the API's.

``constants.RESERVED_FIELD_KEYS`` derives itself from the ``Record`` model so
it cannot drift when a column is added; the TypeScript mirror in
``components/typeeditor/rules.ts`` is hand-typed and can. This test reads that
file and compares the two sets, so the next column added to ``Record`` fails
here instead of letting the editor accept a key the API refuses.

The same file mirrors ``MAX_KEY_LEN`` and ``MAX_LABEL_LEN`` (review R3 — the
editor used to accept a 65-character key the API bounces with a 422 whose
``field`` is the over-long key itself, which no row input can claim). Those
two numbers are pinned here for the same reason and in the same place.
"""

from __future__ import annotations

import re
from pathlib import Path

from sm_records import constants

_RULES = (
    Path(__file__).resolve().parents[1] / "sm_records" / "components" / "typeeditor" / "rules.ts"
)


def _ts_reserved_keys() -> frozenset[str]:
    source = _RULES.read_text(encoding="utf-8")
    match = re.search(
        r"export const RESERVED_FIELD_KEYS[^=]*=\s*new Set\(\[(.*?)\]\)", source, re.S
    )
    assert match, "RESERVED_FIELD_KEYS Set literal not found in rules.ts"
    body = match.group(1)
    keys = set(re.findall(r"'([^']+)'", body))
    if "ORPHANED_KEY" in body:
        keys.add(constants.ORPHANED_KEY)
    return frozenset(keys)


def test_editor_reserved_keys_match_api() -> None:
    ts, py = _ts_reserved_keys(), constants.RESERVED_FIELD_KEYS
    assert ts == py, f"only in rules.ts: {sorted(ts - py)}; only in constants: {sorted(py - ts)}"


def _ts_const(name: str) -> int:
    source = _RULES.read_text(encoding="utf-8")
    match = re.search(rf"export const {name}\s*=\s*(\d+)\s*;", source)
    assert match, f"{name} not found in rules.ts"
    return int(match.group(1))


def test_editor_length_caps_match_api() -> None:
    assert _ts_const("MAX_KEY_LEN") == constants.MAX_KEY_LEN
    assert _ts_const("MAX_LABEL_LEN") == constants.MAX_LABEL_LEN
