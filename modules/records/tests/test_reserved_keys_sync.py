"""The schema editor's reserved-key list must equal the API's.

``constants.RESERVED_FIELD_KEYS`` derives itself from the ``Record`` model so
it cannot drift when a column is added; the TypeScript mirror in
``components/typeeditor/rules.ts`` is hand-typed and can. This test reads that
file and compares the two sets, so the next column added to ``Record`` fails
here instead of letting the editor accept a key the API refuses.
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
