"""Which links an article body may carry, checked on save and bundle restore (#364).

A copy of ``pagebuilder.content.links`` (#354): news cannot import pagebuilder,
so ``scripts/tests/parity_families.py`` keeps the two copies aligned.

* no control character anywhere;
* after leading whitespace, either no scheme at all — ``/about``, ``#top``,
  ``?q=1``, ``./x``, ``contact``, ``//cdn.example`` — or one of ``http``,
  ``https``, ``mailto`` and ``tel``.

Every prop named ``href`` or ending in ``Href``, every Markdown link target in
any string prop, every ``Sources`` line's URL cell, and the ``url`` of an
``Embed``, ``Video`` or ``Audio`` block (:data:`FRAME_SOURCES`, restricted to
``http(s)`` or scheme-less) are checked.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator
from typing import Any

SAFE_SCHEMES: frozenset[str] = frozenset({"http", "https", "mailto", "tel"})
FRAME_SCHEMES: frozenset[str] = frozenset({"http", "https"})
#: Block type → props that load into a frame or player (client: ``safeFrameSrc``).
FRAME_SOURCES: dict[str, tuple[str, ...]] = {
    "Embed": ("url",),
    "Video": ("url",),
    "Audio": ("url",),
}

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*):")
# The client's HREF_SOURCE: one level of balanced parentheses, so
# ``.../Foo_(bar)`` is one target rather than a truncated one.
_HREF = r"(?:[^\s()]|\([^\s()]*\))+"
_MD_IMAGE = re.compile(rf"!\[[^\]]*\]\({_HREF}\)")
_MD_LINK = re.compile(rf"\[[^\]]+\]\(({_HREF})\)")
_SHOWN = 80


class UnsafeLinkError(ValueError):
    """A block carries a link outside the allow-list; the message names where."""


def is_safe_href(value: str, *, schemes: Collection[str] = SAFE_SCHEMES) -> bool:
    """Whether *value* may be written into ``<a href>`` (or, with *schemes*, a frame)."""
    if _CONTROL.search(value):
        return False
    scheme = _SCHEME.match(value.lstrip())
    if scheme is None:
        return True
    name = scheme.group(1).lower()
    return name in schemes


def _is_link_key(key: str) -> bool:
    return key == "href" or key.endswith("Href")


def _markdown_targets(text: str) -> Iterator[str]:
    """The target of every ``[label](target)``; an image's own source is not one."""
    # A linked image ``[![alt](src)](href)`` keeps its outer link once the
    # image inside it is blanked out.
    yield from _MD_LINK.findall(_MD_IMAGE.sub("img", text))


_Found = tuple[str, str, str, frozenset[str]]


def _sources_links(block: str, items: str) -> Iterator[_Found]:
    """Each URL cell in a ``Sources`` block's ``label | href`` textarea."""
    non_empty = [line.strip() for line in items.split("\n") if line.strip()]
    for index, line in enumerate(non_empty):
        if "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        href = " | ".join(parts[1:])
        if href:
            yield block, f"items[{index}]", href, SAFE_SCHEMES


def _walk(node: Any, block: str, path: str) -> Iterator[_Found]:
    """Yield ``(block, field path, link, allowed schemes)`` for every link in *node*.

    Every key of every dict is visited. Recognising a block (a string ``type``
    beside a dict ``props``) only names it in the message: a block-shaped dict
    planted next to a document's ``content`` must not end the walk there.
    """
    if isinstance(node, dict):
        props = node.get("props")
        is_block = isinstance(node.get("type"), str) and isinstance(props, dict)
        if is_block:
            name = f"{node['type']} ({props.get('id') or 'no id'})"
            for key in FRAME_SOURCES.get(node["type"], ()):
                if isinstance(props.get(key), str):
                    yield name, key, props[key], FRAME_SCHEMES
            if node["type"] == "Sources" and isinstance(props.get("items"), str):
                yield from _sources_links(name, props["items"])
            yield from _walk(props, name, "")
        for key, value in node.items():
            if is_block and key == "props":
                continue
            field = f"{path}.{key}" if path else str(key)
            if isinstance(value, str) and _is_link_key(str(key)):
                yield block, field, value, SAFE_SCHEMES
            else:
                yield from _walk(value, block, field)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, block, f"{path}[{index}]")
    elif isinstance(node, str):
        for target in _markdown_targets(node):
            yield block, path, target, SAFE_SCHEMES


def check_links(
    data: Any, *, label: str = "", extra_schemes: Collection[str] = ()
) -> None:
    """Raise :class:`UnsafeLinkError` naming the first block with a refused link.

    *data* is a Puck document (``content``, ``zones``, ``root``) or any part of
    one; *label* prefixes the message (``"header_data: "``). *extra_schemes*
    admits a scheme only a caller knows about — a bundle's ``asset:`` sentinel.
    """
    allowed = {
        SAFE_SCHEMES: SAFE_SCHEMES | frozenset(extra_schemes),
        FRAME_SCHEMES: FRAME_SCHEMES | frozenset(extra_schemes),
    }
    for block, field, link, schemes in _walk(data, "root", ""):
        if is_safe_href(link, schemes=allowed[schemes]):
            continue
        shown = link if len(link) <= _SHOWN else f"{link[:_SHOWN]}…"
        raise UnsafeLinkError(
            f"{label}Block {block}, field {field or 'text'}: {shown!r} is not an allowed "
            f"link. Use an {'http(s)' if schemes == FRAME_SCHEMES else 'http(s), mailto or tel'} "
            "address, or a relative one (/page, #anchor)."
        )


def checked(data: Any) -> Any:
    """:func:`check_links` as a pydantic ``AfterValidator``: *data*, or a 422."""
    check_links(data)
    return data
