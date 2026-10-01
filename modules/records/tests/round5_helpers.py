"""The two field builders both halves of the Phase 5 core-review suite use.

Its own module rather than ``conftest.py`` because these are builders and not
fixtures, and because the two test files are one suite split for the
300-line cap — see ``test_review_fixes_round5.py``.
"""

from __future__ import annotations


def text(key: str, **extra) -> dict:
    return {"key": key, "type": "text", "label": key.title(), "indexed": True, **extra}


def rel(key: str, target: str, **options) -> dict:
    return {
        "key": key,
        "type": "relation",
        "label": key.title(),
        "options": {"target_type": target, **options},
    }
