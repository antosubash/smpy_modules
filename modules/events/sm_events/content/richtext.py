"""Allow-list rich-text re-serialiser: the output is built, never filtered.

Only :data:`ALLOWED_TAGS` are emitted, with no attribute except ``a[href]``, which
must be an absolute ``http``, ``https`` or ``mailto`` URL. All text is escaped.
Dropped-content tags lose their contents, any other tag is unwrapped, and nesting
is capped. The output is idempotent: ``clean(clean(x)) == clean(x)``.

The structure is well-formed whatever the input: a block inside a ``p`` or a heading is
hoisted out of it (the text around it keeps a block of its own), and a ``<br>`` that
ends a block and a block with no text in it are dropped.

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


def safe_href(value: str | None) -> str | None:
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


BLOCKS = frozenset({"p", "ul", "ol", "li", "blockquote", "h2", "h3"})
TEXT_BLOCKS = frozenset({"p", "h2", "h3"})
"""Blocks that hold only inline content: a block inside one is hoisted out, and the
text around it goes into a block of the same kind (``<p>a<ul>..</ul>b</p>`` is
``<p>a</p><ul>..</ul><p>b</p>``)."""


class _El:
    __slots__ = ("href", "kids", "name")

    def __init__(self, name: str, href: str | None = None) -> None:
        self.name = name
        self.href = href
        self.kids: list[_El | str] = []


def _has_content(node: _El | str) -> bool:
    if isinstance(node, str):
        return bool(node.strip())
    return any(_has_content(kid) for kid in node.kids)


def _trim_tail(kids: list[_El | str]) -> list[_El | str]:
    """Without the ``<br>`` (and blanks around it) that ends a block; an empty block
    that follows it is not there at all, so it cannot hide it."""
    kids = [
        k for k in kids if not (isinstance(k, _El) and k.name in BLOCKS and not _has_content(k))
    ]
    end = len(kids)
    while end and (
        (isinstance(kids[end - 1], str) and not str(kids[end - 1]).strip())
        or (isinstance(kids[end - 1], _El) and kids[end - 1].name == "br")  # type: ignore[union-attr]
    ):
        end -= 1
    return kids[:end]


def _open(node: _El) -> str:
    if node.name == "a" and node.href is not None:
        return f'<a href="{html.escape(node.href, quote=True)}">'
    return f"<{node.name}>"


def _render(node: _El | str) -> str:
    if isinstance(node, str):
        return html.escape(node, quote=False)
    if node.name == "br":
        return "<br>"
    if node.name not in BLOCKS:
        return f"{_open(node)}{''.join(_render(kid) for kid in node.kids)}</{node.name}>"
    if node.name in TEXT_BLOCKS:
        return _render_text_block(node)
    return _render_block(node, node.kids)


def _render_block(node: _El, kids: list[_El | str]) -> str:
    kids = _trim_tail(kids)
    if not any(_has_content(kid) for kid in kids):
        return ""  # an empty block (an editor's leftover) is not kept
    return f"{_open(node)}{''.join(_render(kid) for kid in kids)}</{node.name}>"


def _render_text_block(node: _El) -> str:
    out: list[str] = []
    run: list[_El | str] = []
    for kid in node.kids:
        if isinstance(kid, _El) and kid.name in BLOCKS:
            out.append(_render_block(node, run))
            out.append(_render(kid))
            run = []
        else:
            run.append(kid)
    out.append(_render_block(node, run))
    return "".join(out)


class _Cleaner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _El("")
        self.stack: list[tuple[str, _El | None]] = []  # (name, kept element; None: unwrapped)
        self.drop: str | None = None
        self.drop_n = 0
        self.n_emitted = 0

    def _parent(self) -> _El:
        for _, node in reversed(self.stack):
            if node is not None:
                return node
        return self.root

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
            self._parent().kids.append(_El("br"))
            return
        if len(self.stack) >= MAX_OPEN:
            return
        href = None
        if name == "a":
            href = safe_href(next((v for k, v in attrs if k == "href"), None))
            if href is None or any(n == "a" for n, _ in self.stack):
                self.stack.append(("a", None))  # unwrapped, but its </a> must not close another
                return
        if self.n_emitted >= MAX_DEPTH:
            self.stack.append((name, None))
            return
        node = _El(name, href)
        self._parent().kids.append(node)
        self.stack.append((name, node))
        self.n_emitted += 1

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
                    _, node = self.stack.pop()
                    if node is not None:
                        self.n_emitted -= 1
                return

    def handle_data(self, data: str) -> None:
        if not self.drop:
            self._parent().kids.append(_CONTROLS.sub("", data))

    def finish(self) -> str:
        self.close()
        return "".join(_render(kid) for kid in self.root.kids)


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
