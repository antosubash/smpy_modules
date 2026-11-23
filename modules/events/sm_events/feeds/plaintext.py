"""Plain text from a stored description.

The stored HTML is re-cleaned first (:func:`sm_events.content.richtext.clean`: clean at save
*and* wherever it is used), so nothing but the allow-list reaches the parser. Blocks become
paragraphs separated by a blank line, list items ``- `` (``1. `` in an ordered list), ``<br>`` a
line break, a link ``text (href)`` (once, when the text is the address), and entities are decoded.
Used for the ``DESCRIPTION`` of a feed, meta descriptions and JSON-LD.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from sm_events.content.richtext import clean

__all__ = ["to_text"]

_BLOCKS = frozenset({"p", "h2", "h3", "blockquote", "ul", "ol"})
_ELLIPSIS = "…"


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paras: list[str] = []  # finished blocks
        self.cur: list[str] = []
        self.lists: list[list[int]] = []  # one counter per open list; 0 = unordered
        self.hrefs: list[str | None] = []
        self.link_text: list[list[str]] = []

    def _flush(self) -> None:
        text = "".join(self.cur).strip()
        self.cur = []
        if text:
            self.paras.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("ul", "ol"):
            self._flush()
            self.lists.append([0 if tag == "ul" else 1])
        elif tag == "li":
            self._flush()
            if self.lists:
                counter = self.lists[-1]
                self.cur.append("- " if counter[0] == 0 else f"{counter[0]}. ")
                counter[0] += 1 if counter[0] else 0
        elif tag in _BLOCKS:
            self._flush()
        elif tag == "br":
            self.cur.append("\n")
        elif tag == "a":
            self.hrefs.append(dict(attrs).get("href"))
            self.link_text.append([])

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.hrefs:
            href, parts = self.hrefs.pop(), self.link_text.pop()
            text = "".join(parts)
            if href and href != text and text:
                text = f"{text} ({href})"
            elif href and not text:
                text = href
            self._emit(text)
        elif tag in ("ul", "ol"):
            self._flush()
            if self.lists:
                self.lists.pop()
        elif tag == "li" or tag in _BLOCKS:
            self._flush_item(tag)

    def _flush_item(self, tag: str) -> None:
        text = "".join(self.cur).strip()
        self.cur = []
        if not text:
            return
        self.paras.append(text)
        if tag == "li":
            self.paras[-1] = "\x00" + text  # marks a list item: joined with one newline

    def _emit(self, text: str) -> None:
        (self.link_text[-1] if self.link_text else self.cur).append(text)

    def handle_data(self, data: str) -> None:
        self._emit(data)


def _join(paras: list[str]) -> str:
    out: list[str] = []
    for index, para in enumerate(paras):
        item = para.startswith("\x00")
        para = para.lstrip("\x00")
        if index:
            previous_item = paras[index - 1].startswith("\x00")
            out.append("\n" if item and previous_item else "\n\n")
        out.append(para)
    return "".join(out)


def _cut(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    room = max_chars - len(_ELLIPSIS)
    head = text[:room]
    if " " in head and text[room] != " ":
        head = head[: head.rindex(" ")]
    return head.rstrip() + _ELLIPSIS


def to_text(html: str, *, max_chars: int | None = None) -> str:
    """The description as plain text; ``max_chars`` cuts at a word boundary and adds ``…``."""
    parser = _Text()
    parser.feed(clean(html))
    parser.close()
    parser._flush()
    text = re.sub(r"[ \t]+\n", "\n", _join(parser.paras))
    return text if max_chars is None else _cut(text, max_chars)
