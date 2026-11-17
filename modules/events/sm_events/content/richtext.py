"""Allow-list rich-text re-serialiser: the output is built, never filtered.

Only :data:`ALLOWED_TAGS` are emitted, with no attribute except ``a[href]``, which
must be an absolute ``http``, ``https`` or ``mailto`` URL. All text is escaped.
Dropped-content tags lose their contents, any other tag is unwrapped, and nesting
is capped. The output is idempotent: ``clean(clean(x)) == clean(x)``.

Applied at **save**, and again wherever the stored HTML is rendered: nothing
renders what a request sent. The structure follows newsletter's cleaner, which
this module deliberately does not import.
"""

from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urlsplit

from sm_events.core import constants
from sm_events.core.errors import DescriptionTooLong

__all__ = ["ALLOWED_TAGS", "DROP_CONTENT", "clean"]

ALLOWED_TAGS = frozenset(
    {"p", "br", "strong", "em", "u", "s", "a", "ul", "ol", "li", "blockquote", "h2", "h3"}
)
DROP_CONTENT = frozenset(
    {"script", "style", "iframe", "object", "embed", "template", "svg", "math", "head"}
    | {"title", "noscript"}
)
RENAME = {"b": "strong", "i": "em"}
SCHEMES = frozenset({"http", "https", "mailto"})
MAX_DEPTH = 20
MAX_OPEN = 200  # open elements tracked; past it a start tag is treated as unknown
HREF_MAX = 2048
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BROWSER_STRIPS = re.compile(r"[\t\n\r]")
_EDGE = " \t\n\r\x0c\x00"
_BAD_CATEGORIES = frozenset({"Cc", "Cf", "Zs", "Zl", "Zp", "Cs", "Co", "Cn"})


def _href(value: str | None) -> str | None:
    """The URL a browser would follow, or ``None``. Tabs and newlines inside are
    dropped first (a browser drops them too, so ``jav&#9;ascript:`` is read the
    way it will be run); anything else invisible, any space and any control or
    format character refuses the link."""
    if value is None:
        return None
    candidate = _BROWSER_STRIPS.sub("", value.strip(_EDGE))
    if not candidate or len(candidate) > HREF_MAX:
        return None
    if any(unicodedata.category(ch) in _BAD_CATEGORIES for ch in candidate):
        return None
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if parts.scheme.lower() not in SCHEMES:
        return None
    if parts.scheme.lower() == "mailto":
        return candidate if parts.path else None
    return candidate if parts.netloc and parts.hostname else None


class _Cleaner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[tuple[str, bool]] = []  # (name, emitted)
        self.drop: str | None = None
        self.drop_n = 0
        self.n_emitted = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.drop:
            if tag == self.drop:
                self.drop_n += 1
            return
        if tag in DROP_CONTENT:
            self.drop, self.drop_n = tag, 1
            return
        name = RENAME.get(tag, tag)
        if name not in ALLOWED_TAGS:
            return
        if name == "br":
            self.out.append("<br>")
            return
        if len(self.stack) >= MAX_OPEN:
            return
        href = None
        if name == "a":
            href = _href(next((v for k, v in attrs if k == "href"), None))
            if href is None or any(n == "a" for n, _ in self.stack):
                self.stack.append(("a", False))  # unwrapped, but its </a> must not close another
                return
        emitted = self.n_emitted < MAX_DEPTH
        self.stack.append((name, emitted))
        if emitted:
            self.n_emitted += 1
            if href is not None:
                self.out.append(f'<a href="{html.escape(href, quote=True)}">')
            else:
                self.out.append(f"<{name}>")

    def handle_endtag(self, tag: str) -> None:
        if self.drop:
            if tag == self.drop:
                self.drop_n -= 1
                if self.drop_n == 0:
                    self.drop = None
            return
        name = RENAME.get(tag, tag)
        if name not in ALLOWED_TAGS or name == "br":
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == name:
                while len(self.stack) > i:
                    n, emitted = self.stack.pop()
                    if emitted:
                        self.n_emitted -= 1
                        self.out.append(f"</{n}>")
                return

    def handle_data(self, data: str) -> None:
        if not self.drop:
            self.out.append(html.escape(_CONTROLS.sub("", data), quote=False))

    def finish(self) -> str:
        self.close()
        while self.stack:
            n, emitted = self.stack.pop()
            if emitted:
                self.out.append(f"</{n}>")
        return "".join(self.out)


def clean(raw: str) -> str:
    """Canonical HTML: allow-listed tags, ``a[href]`` only, text escaped.

    Raises :class:`DescriptionTooLong` for a raw input over
    ``DESCRIPTION_RAW_MAX`` characters or a result over ``DESCRIPTION_MAX``."""
    if len(raw) > constants.DESCRIPTION_RAW_MAX:
        raise DescriptionTooLong
    cleaner = _Cleaner()
    cleaner.feed(raw)
    out = cleaner.finish()
    if len(out) > constants.DESCRIPTION_MAX:
        raise DescriptionTooLong
    return out
