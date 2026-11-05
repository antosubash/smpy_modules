"""Inline styles for the rich-text tags (email clients ignore stylesheets)."""

from __future__ import annotations

import re

FONT = "-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
TEXT_COLOR = "#222222"

TAG_STYLES: dict[str, str] = {
    "p": f"margin:0 0 16px;font-family:{FONT};font-size:16px;line-height:1.5;color:{TEXT_COLOR}",
    "ul": f"margin:0 0 16px;padding-left:24px;font-family:{FONT};font-size:16px;color:{TEXT_COLOR}",
    "ol": f"margin:0 0 16px;padding-left:24px;font-family:{FONT};font-size:16px;color:{TEXT_COLOR}",
    "li": "margin:0 0 4px;line-height:1.5",
    "blockquote": "margin:0 0 16px;padding-left:16px;border-left:3px solid #cccccc;color:#555555",
    "strong": "font-weight:bold",
    "em": "font-style:italic",
    "u": "text-decoration:underline",
    "s": "text-decoration:line-through",
}

_COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def link_style(accent: str) -> str:
    """The link style; ``accent`` must be a hex colour, since it lands in a style attribute."""
    if not _COLOR.match(accent):
        raise ValueError("accent must be a hex colour")
    return f"color:{accent};text-decoration:underline"
