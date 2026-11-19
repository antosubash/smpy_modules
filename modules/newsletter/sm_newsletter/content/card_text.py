"""What every card's snapshot shares: the bounds a card block's text is clipped to, whether an
address would be accepted, and the removal of direction controls.

The block models (``blocks.py``) validate against the same bounds, so a snapshot clipped here
always passes them.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "EXCERPT_MAX",
    "LOCALE_MAX",
    "PLACE_MAX",
    "TITLE_MAX",
    "fits",
    "strip_bidi",
]

TITLE_MAX = 300
EXCERPT_MAX = 1000
LOCALE_MAX = 16
PLACE_MAX = 500

_BIDI = re.compile("[‎‏؜‪-‮⁦-⁩]")


def strip_bidi(value: str) -> str:
    """``value`` without direction marks, embeddings, overrides and isolates: they would reorder
    the text around them in a mail client. Events refuses them in a title, but a snapshot may hold
    text from before that, so the snapshot and the renderer neutralise them themselves."""
    return _BIDI.sub("", value)


def fits(check: Any, value: str) -> bool:
    """Whether the body's address check (``check_link``, ``check_image``) accepts ``value``."""
    try:
        check(value)
    except ValueError:
        return False
    return True
