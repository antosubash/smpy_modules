"""Header-injection guard shared by every field that ends up in a mail header."""

from __future__ import annotations

import unicodedata

# Control characters (C0, DEL, C1 such as U+0085) and the line/paragraph
# separators U+2028/U+2029. Python's email package refuses all of them in a
# header; format characters (Cf) stay allowed so emoji ZWJ sequences work.
_REFUSED = frozenset({"Cc", "Zl", "Zp"})


def check_header_text(value: str, *, field: str) -> str:
    """Refuse line breaks and every control character (categories Cc, Zl, Zp).

    The message names the field and never repeats the value.
    """
    if any(unicodedata.category(ch) in _REFUSED for ch in value):
        raise ValueError(f"{field} must not contain line breaks or control characters")
    return value
