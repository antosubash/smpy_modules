"""The HTML part: a table shell, one row per block, every style inline.

Never a ``<style>`` block, a ``<script>`` or a ``class``: Gmail and Outlook drop
or mangle them. Every ``href``/``src`` is made absolute and then escaped with
``quote=True`` before any merge field is filled in.
"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING, Any

from sm_newsletter.content import richtext
from sm_newsletter.content.render import styles as s
from sm_newsletter.content.render.types import RenderContext
from sm_newsletter.content.urls import absolute

if TYPE_CHECKING:
    # Types only: ``richtext`` imports this package, and ``blocks`` imports
    # ``richtext``, so a runtime import here would be circular. Blocks are told
    # apart by their ``type`` tag instead.
    from sm_newsletter.content.blocks import (
        Block,
        ButtonBlock,
        CardProps,
        HeadingBlock,
        ImageBlock,
    )

_CONTENT_WIDTH = s.WIDTH - 64  # the cell's side padding
_RICH_HREF = re.compile(r'<a href="([^"]*)">')
_TABLE = 'role="presentation" border="0" cellpadding="0" cellspacing="0"'


def esc(value: str) -> str:
    """Author text whose merge tags are meant (headings, labels, alt text)."""
    return html.escape(value, quote=True)


def inert(value: str) -> str:
    """Text from elsewhere (cards, branding, settings): escaped, and no ``{{`` survives
    to be read as a merge tag."""
    return html.escape(value, quote=True).replace("{", "&#123;")


def url(base: str, value: str) -> str:
    return html.escape(absolute(base, value), quote=True)


def rich_source(raw: str, base: str) -> str:
    """``clean`` output with every link made absolute; still valid ``clean`` output."""

    def repl(m: re.Match[str]) -> str:
        return f'<a href="{url(base, html.unescape(m.group(1)))}">'

    return _RICH_HREF.sub(repl, richtext.clean(raw))


def _heading(b: HeadingBlock) -> str:
    p = b.props
    return (
        f'<h{p.level} style="{s.HEADING[p.level]};text-align:{p.align}">{esc(p.text)}</h{p.level}>'
    )


def _image(b: ImageBlock, ctx: RenderContext) -> str:
    p = b.props
    width = min(p.width, _CONTENT_WIDTH)
    img = (
        f'<img src="{url(ctx.content_base, p.src)}" width="{width}" alt="{esc(p.alt)}"'
        f' style="{s.fluid_image(width)}">'
    )
    return f'<a href="{url(ctx.content_base, p.href)}">{img}</a>' if p.href else img


def _button(b: ButtonBlock, ctx: RenderContext) -> str:
    p, accent = b.props, esc(ctx.branding.accent)
    return (
        f'<table {_TABLE} align="{p.align}"><tr>'
        f'<td align="center" bgcolor="{accent}"'
        f' style="border-radius:6px;background-color:{accent}">'
        f'<a href="{url(ctx.content_base, p.href)}" style="{s.BUTTON_LINK}">{esc(p.label)}</a>'
        "</td></tr></table>"
    )


def _card(p: CardProps, ctx: RenderContext) -> str:
    href = url(ctx.content_base, p.url)
    out = ""
    if p.image_url:
        out += (
            f'<a href="{href}"><img src="{url(ctx.content_base, p.image_url)}"'
            f' width="{_CONTENT_WIDTH}" alt="{inert(p.title)}"'
            f' style="{s.fluid_image(_CONTENT_WIDTH)}"></a>'
        )
    if p.title:
        title_link = f"color:{s.TEXT_COLOR};text-decoration:none"
        out += (
            f'<h3 style="{s.CARD_TITLE}">'
            f'<a href="{href}" style="{title_link}">{inert(p.title)}</a></h3>'
        )
    if p.excerpt:
        out += f'<p style="{s.CARD_TEXT}">{inert(p.excerpt)}</p>'
    more = f"{s.CARD_LINK_BASE};{s.accent_link(ctx.branding.accent)}"
    return out + f'<a href="{href}" style="{more}">{inert(ctx.footer.read_more)}</a>'


_DIVIDER = (
    f'<table {_TABLE} width="100%"><tr>'
    f'<td style="border-top:1px solid {s.RULE};font-size:0;line-height:0">&nbsp;</td>'
    "</tr></table>"
)


def _inner(b: Any, ctx: RenderContext) -> str:
    kind = b.type
    if kind == "Heading":
        return _heading(b)
    if kind == "RichText":
        cleaned = rich_source(b.props.html, ctx.content_base)
        return richtext.to_email_html(cleaned, accent=ctx.branding.accent)
    if kind == "Image":
        return _image(b, ctx)
    if kind == "Button":
        return _button(b, ctx)
    if kind == "Divider":
        return _DIVIDER
    if kind == "Spacer":
        px = s.SPACER_PX[b.props.size]
        return f'<div style="height:{px}px;line-height:{px}px;font-size:0">&nbsp;</div>'
    if kind in ("ArticleCard", "PageCard"):
        return _card(b.props, ctx)
    raise TypeError(f"unknown block {kind!r}")  # the union is closed


def block(b: Block, ctx: RenderContext) -> str:
    """One ``<tr>`` for one block."""
    return f'<tr><td style="{s.CELL}">{_inner(b, ctx)}</td></tr>'


def header(ctx: RenderContext) -> str:
    brand = ctx.branding
    if brand.logo_url:
        inner = (
            f'<img src="{url(ctx.public_base, brand.logo_url)}" width="{s.LOGO_WIDTH}"'
            f' alt="{inert(brand.app_name)}" style="{s.LOGO}">'
        )
    else:
        inner = f'<span style="{s.APP_NAME}">{inert(brand.app_name)}</span>'
    return f'<tr><td style="{s.HEADER_CELL}">{inner}</td></tr>'


_DOCTYPE = (
    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"'
    ' "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">'
)


def shell(*, subject: str, preheader: str, locale: str, rows: list[str]) -> str:
    """The document around the rows; ``subject`` and ``preheader`` keep their merge tags."""
    hidden = "display:none;max-height:0;overflow:hidden;mso-hide:all"
    inner_style = f"width:100%;max-width:{s.WIDTH}px;background-color:{s.BODY_BG}"
    return "\n".join(
        [
            _DOCTYPE,
            f'<html xmlns="http://www.w3.org/1999/xhtml" lang="{esc(locale)}">',
            "<head>",
            '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
            f"<title>{esc(subject)}</title>",
            "</head>",
            f'<body style="margin:0;padding:0;background-color:{s.PAGE_BG}">',
            f'<div style="{hidden}">{esc(preheader)}</div>',
            f'<table {_TABLE} width="100%" bgcolor="{s.PAGE_BG}"'
            f' style="background-color:{s.PAGE_BG}">',
            '<tr><td align="center" style="padding:24px 8px">',
            f'<table {_TABLE} width="{s.WIDTH}" bgcolor="{s.BODY_BG}" style="{inner_style}">',
            *rows,
            "</table>",
            "</td></tr>",
            "</table>",
            "</body>",
            "</html>",
            "",
        ]
    )
