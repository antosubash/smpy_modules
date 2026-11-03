"""Header-injection guard shared by every field that ends up in a mail header."""

from __future__ import annotations


def check_header_text(value: str, *, field: str) -> str:
    """Refuse CR, LF and every other control character (U+0000-U+001F, U+007F).

    The message names the field and never repeats the value.
    """
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ValueError(f"{field} must not contain line breaks or control characters")
    return value
