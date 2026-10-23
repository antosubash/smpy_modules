"""Two field builders — an indexed ``text`` and a ``relation`` — shared by
``test_relation_retarget_reindex.py``, ``test_preview_report_reuse.py``,
``test_import_match_keys.py`` and ``test_expand_alignment.py``.

Its own module rather than ``conftest.py`` because these are builders and not
fixtures.
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
