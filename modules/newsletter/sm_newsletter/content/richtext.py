"""Allow-list rich-text re-serialiser: the output is built, never filtered.

Only ``ALLOWED_TAGS`` are emitted, with no attributes except ``a[href]``, which
must pass ``urls.check_link``. All text is escaped. Dropped-content tags lose
their contents; any other tag is unwrapped. A duplicate ``href`` keeps the
first, as browsers do. Applied at save and again at render.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from sm_newsletter.content.render.styles import TAG_STYLES, link_style
from sm_newsletter.content.urls import check_link

ALLOWED_TAGS = frozenset({"p", "br", "strong", "em", "u", "s", "a", "ul", "ol", "li", "blockquote"})
DROP_CONTENT = frozenset(
    {"script", "style", "iframe", "object", "embed", "template", "svg", "math", "head"}
    | {"title", "noscript"}
)
RENAME = {"b": "strong", "i": "em"}
MAX_DEPTH = 20
MAX_OPEN = 200  # open elements tracked; past it a start tag is treated as unknown
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_STRIP_INNER = re.compile(r"[\t\n\r\x00-\x1f\x7f]")
_NORMAL_WEIGHT = re.compile(r"font-weight:\s*(normal|400)", re.I)


def _href(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = _STRIP_INNER.sub("", value.strip(" \t\n\r\x0c\x00"))
    try:
        return check_link(candidate)
    except ValueError:
        return None


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
        if tag == "b" and any(_NORMAL_WEIGHT.search(v or "") for k, v in attrs if k == "style"):
            return  # Google Docs wraps a paste in <b style="font-weight:normal">
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
    """Canonical, attribute-free except ``a[href]``; ``clean(clean(x)) == clean(x)``."""
    cleaner = _Cleaner()
    cleaner.feed(raw)
    return cleaner.finish()


_TAG = re.compile(r'<(/?)([a-z]+)((?: href="[^"]*")?)>')


def to_email_html(cleaned: str, *, accent: str) -> str:
    """The same tree with each tag's inline style. Input must be ``clean`` output."""
    link = link_style(accent)

    def style(m: re.Match[str]) -> str:
        closing, name, href = m.groups()
        if closing or name == "br":
            return m.group(0)
        css = link if name == "a" else TAG_STYLES[name]
        return f'<{name}{href} style="{css}">'

    return _TAG.sub(style, cleaned)


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []  # (kind, text); kind "p" or "li<list number>"
        self.buf = ""
        self.lists: list[list[int]] = []  # [ordered?, counter]
        self.n_lists = 0
        self.href: list[str | None] = []
        self.label = ""
        self.item = ""

    def _flush(self) -> None:
        text = "\n".join(" ".join(line.split()) for line in self.buf.split("\n")).strip("\n ")
        if text:
            self.blocks.append((f"li{self.n_lists}" if self.item else "p", self.item + text))
        self.buf, self.item = "", ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.buf += "\n"
        elif tag in ("ul", "ol"):
            self._flush()
            self.lists.append([int(tag == "ol"), 0])
            self.n_lists += 1
        elif tag == "li":
            self._flush()
            lst = self.lists[-1] if self.lists else [0, 0]
            lst[1] += 1
            self.item = "  " * max(len(self.lists) - 1, 0) + (f"{lst[1]}. " if lst[0] else "- ")
        elif tag in ("p", "blockquote"):
            self._flush()
        elif tag == "a":
            self.href.append(next((v for k, v in attrs if k == "href"), None))
            self.label = self.buf
            self.buf = ""

    def handle_endtag(self, tag: str) -> None:
        if tag in ("p", "blockquote", "li"):
            self._flush()
        elif tag in ("ul", "ol") and self.lists:
            self._flush()
            self.lists.pop()
        elif tag == "a" and self.href:
            href, label = self.href.pop(), " ".join(self.buf.split())
            self.buf = self.label + (label if not href or label == href else f"{label} ({href})")
            self.label = ""

    def handle_data(self, data: str) -> None:
        self.buf += data


def to_text(cleaned: str) -> str:
    """Plain-text alternative: blank line between blocks, list markers, ``label (url)``."""
    parser = _Text()
    parser.feed(cleaned)
    parser.close()
    parser._flush()
    out = ""
    for i, (kind, text) in enumerate(parser.blocks):
        if i:
            out += "\n" if kind != "p" and parser.blocks[i - 1][0] == kind else "\n\n"
        out += text
    return out
