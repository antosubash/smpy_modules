"""Which characters never belong in a name or a line of text, and how to strip them.

Shared by the request schemas (which refuse them), the importer (which strips them from a file)
and the plugin validator (which strips them from a title).
"""

from __future__ import annotations

import unicodedata

__all__ = [
    "BIDI",
    "CONTROL",
    "INVISIBLE",
    "LINE_SEPARATORS",
    "MULTILINE_OK",
    "strip_unsafe",
]

CONTROL = "Cc"
"""Unicode category of the C0 and C1 controls, NUL, tab, newline and DEL."""
MULTILINE_OK = frozenset("\n\r\t")
BIDI = frozenset("\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
"""Direction marks and embeddings/overrides/isolates: they reorder the text
around a name when it is shown in a sentence."""
LINE_SEPARATORS = frozenset("\u2028\u2029")
INVISIBLE = frozenset("\u200b\u2060\ufeff")
"""Zero-width space, word joiner and BOM: they make a name that looks empty or
that differs from another one by nothing visible. U+200C and U+200D (the
zero-width non-joiner and joiner) stay allowed: Persian, Indic scripts and emoji
sequences need them."""


def strip_unsafe(value: str, *, newlines: bool = False) -> str:
    """``value`` without what a single line refuses (``newlines``: what free text refuses),
    for text taken from somewhere that is not a person typing it (an imported file, a plugin),
    where refusing the whole value would lose an event over one stray control character."""
    allowed = MULTILINE_OK if newlines else frozenset()
    extra = BIDI if newlines else BIDI | LINE_SEPARATORS | INVISIBLE
    return "".join(
        ch
        for ch in value
        if not ((unicodedata.category(ch) == CONTROL and ch not in allowed) or ch in extra)
    )
