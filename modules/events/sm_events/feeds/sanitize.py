"""Text on its way into a feed: one function per kind of property, so no row, however it was
written, can break the file or add a property to it.

The API refuses control characters in names and titles, but a row can reach the database another
way (an import, a script), and ``icalendar`` neither accepts a line break in a single-line value
(it asserts, which ``python -O`` removes, leaving ``N\\r\\nX-EVIL:1`` to inject a property) nor
removes a lone carriage return or a NUL. Every value passes through :func:`single_line` or
:func:`multi_line` before it reaches the library.
"""

from __future__ import annotations

import re

__all__ = ["multi_line", "single_line"]

# Line breaks in every spelling: CRLF, CR, LF, VT, FF, NEL and the Unicode separators.
_BREAK = re.compile(r"\r\n|[\r\n\x0b\x0c\x85" + chr(0x2028) + chr(0x2029) + "]")
# Everything else that is a control: C0 (tab apart), DEL and C1.
_CONTROL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")


def single_line(value: str | None) -> str:
    """``value`` on one line: each line break is a space, other controls are dropped."""
    return _CONTROL.sub("", _BREAK.sub(" ", value or ""))


def multi_line(value: str | None) -> str:
    """``value`` with ``\\n`` the only line break and no other control (tab apart)."""
    return _CONTROL.sub("", _BREAK.sub("\n", value or ""))
