"""The public frame's own few words, in the *page's* language (#89).

The console's strings follow the reader's UI language (the ``locale`` cookie,
``Accept-Language``), and the host ships only that one catalogue to the
browser. The public site's frame cannot: ``/de/p/x`` is a German address, and
its "skip to content" link and its not-found page have to be German for a
visitor whose browser says English — the same rule the page's own content
follows. So the server reads them from this module's catalogue for the
content locale and sends them with the page.

Falls back from ``de-at`` to ``de`` to English, so a content locale this
module has no catalogue for still gets words rather than keys.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from pagebuilder.locales import LOCALE_PATTERN

_DIR = Path(__file__).parent / "locales"
_FALLBACK = "en"


@cache
def _public_tree(lang: str) -> dict[str, Any] | None:
    # The pattern is what keeps a tag from naming a path: no dots, no slashes.
    if not LOCALE_PATTERN.match(lang):
        return None
    path = _DIR / f"{lang}.json"
    if not path.is_file():
        return None
    tree = json.loads(path.read_text(encoding="utf-8")).get("public")
    return tree if isinstance(tree, dict) else None


def public_copy(locale: str) -> dict[str, Any]:
    """The skip link and not-found strings in ``locale``.

    Not the draft bar's: that is the editor's chrome and speaks the console's
    language, through the UI catalogue like every other admin string.
    """
    lowered = locale.lower()
    for lang in (lowered, lowered.split("-")[0], _FALLBACK):
        tree = _public_tree(lang)
        if tree is not None:
            return {
                "skip_to_content": tree["skip_to_content"],
                "not_found": dict(tree["not_found"]),
            }
    raise LookupError(f"pagebuilder: no public strings for {locale!r} or {_FALLBACK!r}")
