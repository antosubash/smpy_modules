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


def is_color(value: str) -> bool:
    return _COLOR.fullmatch(value) is not None


def link_style(accent: str) -> str:
    """The link style; ``accent`` must be a hex colour, since it lands in a style attribute."""
    if not is_color(accent):
        raise ValueError("accent must be a hex colour")
    return f"color:{accent};text-decoration:underline"


# The email shell (table layout; every style inline).
WIDTH = 600
PAGE_BG = "#f4f4f5"
BODY_BG = "#ffffff"
MUTED = "#71717a"
RULE = "#e4e4e7"
LOGO_WIDTH = 200
SPACER_PX = {"sm": 8, "md": 16, "lg": 32}

CELL = "padding:0 32px 16px"
HEADER_CELL = "padding:24px 32px"
FOOTER_CELL = f"padding:24px 32px;font-family:{FONT};font-size:12px;line-height:1.5;color:{MUTED}"
HEADING = {
    "1": f"margin:0;font-family:{FONT};font-size:28px;line-height:1.25;color:{TEXT_COLOR}",
    "2": f"margin:0;font-family:{FONT};font-size:22px;line-height:1.3;color:{TEXT_COLOR}",
}
APP_NAME = f"font-family:{FONT};font-size:20px;font-weight:bold;color:{TEXT_COLOR}"


def fluid_image(max_width: int) -> str:
    """An image that shrinks with its cell: ``width:100%`` takes no min-content
    width in an auto-layout table (a bare ``width`` attribute does, which is what
    pushed the email past a phone viewport); Outlook reads the ``width`` attribute."""
    return f"display:block;width:100%;max-width:{max_width}px;height:auto;border:0"


LOGO = fluid_image(LOGO_WIDTH)
BUTTON_LINK = (
    f"display:inline-block;padding:12px 24px;font-family:{FONT};font-size:16px;"
    "font-weight:bold;color:#ffffff;text-decoration:none;border-radius:6px"
)
CARD_TITLE = f"margin:12px 0 8px;font-family:{FONT};font-size:18px;line-height:1.3"
CARD_TEXT = f"margin:0 0 8px;font-family:{FONT};font-size:15px;line-height:1.5;color:{TEXT_COLOR}"
CARD_LINK_BASE = f"font-family:{FONT};font-size:15px;font-weight:bold"


def accent_link(accent: str) -> str:
    """A link in the accent colour; validated like :func:`link_style`."""
    link_style(accent)
    return f"color:{accent};text-decoration:none"
