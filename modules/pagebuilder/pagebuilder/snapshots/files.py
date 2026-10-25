"""Writing bundle documents to disk, one rule for every section.

Moved out of ``capture.py`` so a contributed section (#80) writes its files
through exactly the serialisation pagebuilder's own documents use — sorted
keys, two-space indent, a trailing newline — and so two captures of unchanged
content come out byte-identical whichever module wrote them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pagebuilder import locales


def safe_segment(segment: str) -> str:
    """*segment* with path separators neutralised.

    Slugs and locales are URL segments, but a separator sneaking into one
    would silently write outside ``pages/`` — so they are replaced rather
    than trusted. The authoritative values are inside the document either way.
    """
    return segment.replace("/", "_").replace(chr(92), "_")


def page_filename(slug: str, locale: str) -> str:
    """Filename for a page document, unique across languages.

    The default locale keeps the bare ``{slug}.json`` it has always had, so a
    monolingual site's bundle is byte-for-byte what earlier builds wrote and
    its diffs stay readable. Every other language is prefixed, because two
    languages may legitimately both publish ``about`` and one file cannot hold
    both — without the prefix the second page written would silently replace
    the first, losing a whole document with nothing in the manifest to say so.
    """
    stem = safe_segment(slug)
    return f"{stem}.json" if locales.is_default(locale) else f"{safe_segment(locale)}__{stem}.json"


def write_json(path: Path, payload: Any) -> int:
    """Write *payload* as a bundle document; return the bytes written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sorted keys and a trailing newline so two captures of unchanged content
    # produce byte-identical files — the round-trip test depends on it, and so
    # does a readable diff when a bundle is committed.
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    data = text.encode("utf-8")
    path.write_bytes(data)
    return len(data)


def tree_size(directory: Path) -> int:
    """Total bytes of every file under *directory* (0 when it does not exist)."""
    if not directory.is_dir():
        return 0
    return sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
