"""The plain-text part: one paragraph per block, URLs spelled out."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sm_newsletter.content import richtext
from sm_newsletter.content.render.html import rich_source
from sm_newsletter.content.render.types import RenderContext
from sm_newsletter.content.urls import absolute

if TYPE_CHECKING:  # not at runtime: see ``html``'s note on the import cycle
    from sm_newsletter.content.blocks import Block

_BRACES = re.compile(r"\{(?=\{)")
_UNDERLINE = {"1": "=", "2": "-"}


def inert(value: str) -> str:
    """Text from elsewhere: no ``{{`` survives to be read as a merge tag."""
    return _BRACES.sub("{ ", value)


def block(b: Block, ctx: RenderContext) -> str:
    """The block's text, or ``""`` when it has none (a spacer, an image without alt or link)."""
    base, kind, p = ctx.content_base, b.type, b.props
    if kind == "Heading":
        return f"{p.text}\n{_UNDERLINE[p.level] * len(p.text)}"
    if kind == "RichText":
        return richtext.to_text(rich_source(p.html, base))
    if kind == "Image":
        href = absolute(base, p.href) if p.href else ""
        return f"{p.alt} ({href})" if p.alt and href else p.alt or href
    if kind == "Button":
        return f"{p.label}: {absolute(base, p.href)}"
    if kind == "Divider":
        return "----"
    if kind in ("ArticleCard", "PageCard"):
        lines = [inert(p.title), inert(p.excerpt), absolute(base, p.url)]
        return "\n".join(line for line in lines if line)
    return ""
