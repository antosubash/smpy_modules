"""A stored description as a node tree a client renders without injecting HTML.

No public page in this repo injects a sanitised HTML body. The stored HTML is re-cleaned
(:func:`~sm_events.content.richtext.clean`: clean at save *and* at render) and turned into
``{"t": tag, "c": [children]}`` nodes (plus ``"href"`` on ``a``); text is plain strings, so an
entity is text and never a node. The client maps each allow-listed tag to an element and drops
anything else to its children.

The tree builder re-checks what the clean already guarantees: only :data:`ALLOWED_TAGS`, and an
``a`` keeps its ``href`` only when it is an absolute ``http``, ``https`` or ``mailto`` URL (a link
that fails is unwrapped to its text). Nesting stays within the sanitiser's own cap.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

from sm_events.content.richtext import ALLOWED_TAGS, MAX_DEPTH, clean, safe_href

__all__ = ["Node", "to_tree"]

Node = str | dict[str, Any]
_VOID = frozenset({"br"})


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: list[Node] = []
        self.stack: list[list[Node]] = [self.root]
        self.open: list[str | None] = []  # the tag each open level was made for, None = unwrapped

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_TAGS:
            self.open.append(None)
            return
        node: dict[str, Any] = {"t": tag, "c": []}
        if tag == "a":
            href = safe_href(dict(attrs).get("href"))
            if href is None:
                self.open.append(None)  # unwrapped: its text stays
                return
            node = {"t": "a", "href": href, "c": []}
        self.stack[-1].append(node)
        if tag in _VOID:
            return
        if len(self.stack) > MAX_DEPTH:
            self.open.append(None)
            return
        self.stack.append(node["c"])
        self.open.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID and tag in ALLOWED_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID or not self.open:
            return
        if self.open.pop() is not None and len(self.stack) > 1:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].append(data)


def _prune(nodes: list[Node]) -> list[Node]:
    """Drop elements that hold nothing (an emptied ``p``), keeping ``br``."""
    out: list[Node] = []
    for node in nodes:
        if isinstance(node, dict):
            node["c"] = _prune(node["c"])
            if not node["c"] and node["t"] not in _VOID:
                continue
        out.append(node)
    return out


def to_tree(html: str) -> list[Node]:
    """The re-cleaned ``html`` as nodes; ``[]`` for nothing visible."""
    builder = _Builder()
    builder.feed(clean(html))
    builder.close()
    return [n for n in _prune(builder.root) if not (isinstance(n, str) and not n.strip())]
